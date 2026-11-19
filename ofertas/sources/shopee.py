"""Shopee: ofertas e link de afiliado pela Open API oficial de afiliados.

Credenciais (App ID / Secret): painel de afiliados (affiliate.shopee.com.br) >
menu "Open API" (o acesso precisa ser solicitado e aprovado). O offerLink que a
API devolve já é o seu link de afiliado — não precisa de navegador nem login.
A busca é por palavra-chave (campo "shopee:" de cada grupo no config.yaml).
"""
import hashlib
import json
import logging
import re
import time

import requests

from ..config import config
from ..models import Oferta

log = logging.getLogger("ofertas.shopee")

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
CAMPOS = ("itemId productName priceMin priceMax priceDiscountRate imageUrl "
          "offerLink productLink sales ratingStar shopName")


class ErroShopee(RuntimeError):
    def __init__(self, msg: str, passageiro: bool = False, rede: bool = False):
        super().__init__(msg)
        self.passageiro = passageiro  # erro do servidor da Shopee: vale tentar de novo
        self.rede = rede              # nem chegou na Shopee (sem internet?)


def tem_credenciais() -> bool:
    return bool(config.shopee_app_id and config.shopee_app_secret)


def assinar(app_id: str, secret: str, payload: str, ts: str) -> str:
    """Cabeçalho Authorization da Open API: SHA256(AppId + Timestamp + Payload + Secret)."""
    assinatura = hashlib.sha256(f"{app_id}{ts}{payload}{secret}".encode()).hexdigest()
    return f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}"


# "System Error" (código 10000) e HTTP 5xx são falhas passageiras do servidor da Shopee:
# espera um pouco e tenta de novo antes de desistir
ESPERAS_NOVA_TENTATIVA = (2, 4)


def chamar(query: str, sessao: requests.Session | None = None) -> dict:
    """Consulta a Open API; tenta de novo (até 2 vezes) quando a Shopee falha do lado dela."""
    for espera in ESPERAS_NOVA_TENTATIVA:
        try:
            return _chamar_uma_vez(query, sessao)
        except ErroShopee as e:
            if not e.passageiro:
                raise
            log.debug("Shopee falhou (%s) — tentando de novo em %d s", e, espera)
            time.sleep(espera)
    return _chamar_uma_vez(query, sessao)


def _chamar_uma_vez(query: str, sessao: requests.Session | None = None) -> dict:
    if not tem_credenciais():
        raise ErroShopee("Sem credenciais: preencha SHOPEE_APP_ID e SHOPEE_APP_SECRET no .env "
                         "(painel de afiliados da Shopee > Open API)")
    payload = json.dumps({"query": query}, separators=(",", ":"))
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json",
               "Authorization": assinar(config.shopee_app_id, config.shopee_app_secret, payload, ts)}
    try:
        r = (sessao or requests).post(ENDPOINT, data=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise ErroShopee(f"Shopee fora do ar: {e}", rede=True)
    if r.status_code != 200:
        raise ErroShopee(f"Shopee respondeu HTTP {r.status_code}: {r.text[:300]}",
                         passageiro=r.status_code >= 500)
    dados = r.json()
    if dados.get("errors"):
        codigos = {(e.get("extensions") or {}).get("code") for e in dados["errors"] if isinstance(e, dict)}
        raise ErroShopee(f"Shopee API: {str(dados['errors'])[:300]}", passageiro=10000 in codigos)
    return dados.get("data") or {}


def node_para_oferta(n: dict) -> Oferta | None:
    """Produto da API -> Oferta (o preço antigo é calculado pelo % de desconto)."""
    if not (n.get("itemId") and n.get("productName") and n.get("offerLink")):
        return None
    try:
        preco = float(n.get("priceMin") or 0) or None
    except (TypeError, ValueError):
        preco = None
    desconto = int(n.get("priceDiscountRate") or 0) or None
    original = round(preco / (1 - desconto / 100), 2) if preco and desconto and desconto < 100 else None

    partes = []
    try:
        if float(n.get("ratingStar") or 0) > 0:
            partes.append(f"⭐ {float(n['ratingStar']):.1f}")
    except (TypeError, ValueError):
        pass
    try:
        vendidos = int(n.get("sales") or 0)
        if vendidos:
            partes.append(f"{vendidos:,} vendidos".replace(",", "."))
    except (TypeError, ValueError):
        pass

    return Oferta(
        plataforma="shopee",
        id_produto=str(n["itemId"]),
        titulo=str(n["productName"]).strip(),
        url_produto=n.get("productLink") or n["offerLink"],
        url_afiliado=n["offerLink"],
        preco=preco,
        preco_original=original,
        desconto_pct=desconto,
        imagem=n.get("imageUrl"),
        extra=" · ".join(partes) or None,
    )


def buscar(termo: str, limite: int | None = None, sessao: requests.Session | None = None) -> list[Oferta]:
    """Produtos da busca por palavra-chave, ordenados como no config (padrão: mais vendidos)."""
    limite = max(1, min(int(limite or config.fonte_shopee.get("limite_por_busca", 20)), 50))
    ordem = int(config.fonte_shopee.get("ordenacao", 2))  # 2 = mais vendidos
    query = (f"{{productOfferV2(keyword:{json.dumps(termo, ensure_ascii=False)},"
             f"sortType:{ordem},page:1,limit:{limite}){{nodes{{{CAMPOS}}}}}}}")
    nodes = (chamar(query, sessao).get("productOfferV2") or {}).get("nodes") or []
    ofertas = [o for o in (node_para_oferta(n) for n in nodes) if o]
    log.info("Shopee '%s': %d ofertas", termo, len(ofertas))
    return ofertas


def mais_vendidos(pagina: int = 1, limite: int | None = None, lista: int | None = None) -> list[Oferta]:
    """Lista pronta da Shopee, sem palavra-chave (todas as categorias):
    listType 2 = mais vendidos (padrão; fontes.shopee.lista_geral no config) · 1 = maior comissão."""
    limite = max(1, min(int(limite or config.fonte_shopee.get("limite_por_busca", 20)), 50))
    lista = int(lista or config.fonte_shopee.get("lista_geral", 2))
    query = (f"{{productOfferV2(listType:{lista},sortType:2,page:{max(1, pagina)},limit:{limite})"
             f"{{nodes{{{CAMPOS}}}}}}}")
    nodes = (chamar(query).get("productOfferV2") or {}).get("nodes") or []
    ofertas = [o for o in (node_para_oferta(n) for n in nodes) if o]
    for i, o in enumerate(ofertas, 1):
        o.posicao = (pagina - 1) * limite + i
    log.info("Shopee mais vendidos (página %d): %d ofertas", pagina, len(ofertas))
    return ofertas


# ── cupons: campanhas da Shopee e link curto de afiliado ─────────────

CAMPOS_CAMPANHA = "offerName offerLink imageUrl periodStartTime periodEndTime"


def campanhas(termo: str = "", limite: int = 20) -> list[dict]:
    """Campanhas ativas da Shopee (páginas de ofertas/cupons), já com o link de afiliado.
    Cada item: {"nome", "link", "imagem", "fim" (timestamp ou None)}."""
    filtro = f"keyword:{json.dumps(termo, ensure_ascii=False)}," if termo else ""
    query = (f"{{shopeeOfferV2({filtro}sortType:1,page:1,limit:{max(1, min(limite, 50))})"
             f"{{nodes{{{CAMPOS_CAMPANHA}}}}}}}")
    nodes = (chamar(query).get("shopeeOfferV2") or {}).get("nodes") or []
    agora = time.time()
    achadas = []
    for n in nodes:
        if not (n.get("offerName") and n.get("offerLink")):
            continue
        try:
            fim = int(n.get("periodEndTime") or 0) or None
            inicio = int(n.get("periodStartTime") or 0) or None
        except (TypeError, ValueError):
            fim = inicio = None
        if (fim and fim < agora) or (inicio and inicio > agora):
            continue  # vencida ou ainda não começou
        achadas.append({"nome": str(n["offerName"]).strip(), "link": n["offerLink"],
                        "imagem": n.get("imageUrl") or None, "fim": fim})
    return achadas


def link_afiliado(url: str, sub_id: str = "cupom") -> str:
    """Link curto de afiliado (s.shopee.com.br/...) para qualquer página da Shopee.
    sub_id aparece no relatório da Shopee (ex.: o grupo de onde veio o clique)."""
    sub = re.sub(r"[^A-Za-z0-9]", "", sub_id)[:50] or "bot"
    mutacao = (f"mutation{{generateShortLink(input:{{originUrl:{json.dumps(url)},"
               f"subIds:[{json.dumps(sub)}]}}){{shortLink}}}}")
    link = (chamar(mutacao).get("generateShortLink") or {}).get("shortLink") or ""
    if not link:
        raise ErroShopee("a Shopee não devolveu o link curto de afiliado")
    return link
