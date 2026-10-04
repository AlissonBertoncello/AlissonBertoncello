"""Shopee: ofertas e link de afiliado pela Open API oficial de afiliados.

Credenciais (App ID / Secret): painel de afiliados (affiliate.shopee.com.br) >
menu "Open API" (o acesso precisa ser solicitado e aprovado). O offerLink que a
API devolve já é o seu link de afiliado — não precisa de navegador nem login.
A busca é por palavra-chave (campo "shopee:" de cada grupo no config.yaml).
"""
import hashlib
import json
import logging
import time

import requests

from ..config import config
from ..models import Oferta

log = logging.getLogger("ofertas.shopee")

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
CAMPOS = ("itemId productName priceMin priceMax priceDiscountRate imageUrl "
          "offerLink productLink sales ratingStar shopName")


class ErroShopee(RuntimeError):
    pass


def tem_credenciais() -> bool:
    return bool(config.shopee_app_id and config.shopee_app_secret)


def assinar(app_id: str, secret: str, payload: str, ts: str) -> str:
    """Cabeçalho Authorization da Open API: SHA256(AppId + Timestamp + Payload + Secret)."""
    assinatura = hashlib.sha256(f"{app_id}{ts}{payload}{secret}".encode()).hexdigest()
    return f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={assinatura}"


def chamar(query: str, sessao: requests.Session | None = None) -> dict:
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
        raise ErroShopee(f"Shopee fora do ar: {e}")
    if r.status_code != 200:
        raise ErroShopee(f"Shopee respondeu HTTP {r.status_code}: {r.text[:300]}")
    dados = r.json()
    if dados.get("errors"):
        raise ErroShopee(f"Shopee API: {str(dados['errors'])[:300]}")
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
