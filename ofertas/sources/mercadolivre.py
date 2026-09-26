"""Mercado Livre: ofertas via API oficial (api.mercadolibre.com).

Autenticação: a busca exige um access token. O bot gera um sozinho com o
client_id/client_secret do seu aplicativo (grant_type=client_credentials) e
renova quando expira. Crie o app em https://developers.mercadolivre.com.br/devcenter.
Se preferir, cole um token pronto em ML_ACCESS_TOKEN no .env.
"""
import logging
import time

import requests

from ..config import config
from ..models import Oferta

log = logging.getLogger("ofertas.ml")

API = "https://api.mercadolibre.com"
USER_AGENT = "bot-ofertas-whatsapp/0.1"


class ErroAPI(RuntimeError):
    pass


class ClienteML:
    def __init__(self, client_id: str = "", client_secret: str = "",
                 access_token: str = "", sessao: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token_fixo = access_token
        self._token = ""
        self._expira_em = 0.0
        self.s = sessao or requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    @classmethod
    def do_config(cls) -> "ClienteML":
        return cls(config.ml_client_id, config.ml_client_secret, config.ml_access_token)

    # ── token ────────────────────────────────────────────────────────
    def token(self) -> str:
        if self._token_fixo:
            return self._token_fixo
        if self._token and time.time() < self._expira_em - 60:
            return self._token
        if not (self.client_id and self.client_secret):
            raise ErroAPI("Sem credenciais: preencha ML_CLIENT_ID e ML_CLIENT_SECRET no .env")
        r = self.s.post(f"{API}/oauth/token", timeout=20, data={
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        if r.status_code != 200:
            raise ErroAPI(f"Falha ao gerar token (HTTP {r.status_code}): {r.text[:300]}")
        dados = r.json()
        self._token = dados["access_token"]
        self._expira_em = time.time() + int(dados.get("expires_in", 21600))
        log.info("Mercado Livre: token gerado (válido por %ss)", dados.get("expires_in"))
        return self._token

    def get(self, caminho: str, params: dict | None = None) -> dict:
        r = self.s.get(f"{API}{caminho}", params=params, timeout=30,
                       headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code == 401 and not self._token_fixo:
            self._token = ""  # token expirado/revogado: tenta de novo com um novo
            r = self.s.get(f"{API}{caminho}", params=params, timeout=30,
                           headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code != 200:
            raise ErroAPI(f"GET {caminho} respondeu HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    # ── busca ────────────────────────────────────────────────────────
    def buscar(self, site: str, *, q: str | None = None, categoria: str | None = None,
               limite: int = 50) -> list[dict]:
        params: dict = {"limit": max(1, min(limite, 50))}
        if q:
            params["q"] = q
        if categoria:
            params["category"] = categoria
        return self.get(f"/sites/{site}/search", params).get("results") or []


def _imagem(item: dict) -> str | None:
    img = item.get("thumbnail") or ""
    if not img:
        return None
    img = img.replace("http://", "https://")
    return img.replace("-I.jpg", "-O.jpg")  # thumbnail pequena -> versão grande


def item_para_oferta(item: dict) -> Oferta | None:
    """Converte um resultado da busca da API em Oferta."""
    if not (item.get("id") and item.get("title") and item.get("permalink")):
        return None
    preco = item.get("price")
    original = item.get("original_price")
    venda = item.get("sale_price") or {}
    if venda.get("amount") is not None:
        preco = venda["amount"]
        original = venda.get("regular_amount") or original

    partes = []
    if (item.get("shipping") or {}).get("free_shipping"):
        partes.append("🚚 Frete grátis")
    if item.get("official_store_id"):
        partes.append("🏬 Loja oficial")

    return Oferta(
        plataforma="mercadolivre",
        id_produto=str(item["id"]),
        titulo=item["title"].strip(),
        url=item["permalink"].split("#")[0],
        preco=float(preco) if preco is not None else None,
        preco_original=float(original) if original else None,
        imagem=_imagem(item),
        extra=" · ".join(partes) or None,
    )


def _consultas() -> list[tuple[str, dict]]:
    """[(rótulo, kwargs de ClienteML.buscar)] a partir do config.yaml."""
    fonte = config.fonte_ml
    consultas = [(f"busca '{q}'", {"q": str(q)}) for q in (fonte.get("buscas") or [])]
    cats = fonte.get("categorias") or {}
    if not isinstance(cats, dict):
        cats = {str(c): str(c) for c in cats}
    consultas += [(f"categoria {nome}", {"categoria": str(cid)}) for cid, nome in cats.items()]
    return consultas


def buscar_ofertas(cliente: ClienteML | None = None) -> list[Oferta]:
    """Roda todas as buscas/categorias do config e devolve as ofertas (sem repetição)."""
    cliente = cliente or ClienteML.do_config()
    site = str(config.fonte_ml.get("site") or "MLB")
    limite = int(config.fonte_ml.get("limite_por_busca", 50))
    consultas = _consultas()
    if not consultas:
        log.warning("Mercado Livre: nenhuma busca/categoria no config.yaml")
    ofertas: dict[str, Oferta] = {}
    for rotulo, kwargs in consultas:
        try:
            itens = cliente.buscar(site, limite=limite, **kwargs)
        except ErroAPI as e:
            log.error("Mercado Livre %s: %s", rotulo, e)
            continue
        achadas = [o for o in (item_para_oferta(i) for i in itens) if o]
        for o in achadas:
            ofertas.setdefault(o.id_produto, o)
        log.info("Mercado Livre %s: %d itens", rotulo, len(achadas))
        time.sleep(0.5)
    log.info("Mercado Livre: %d ofertas coletadas", len(ofertas))
    return list(ofertas.values())
