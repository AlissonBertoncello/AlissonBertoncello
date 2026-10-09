"""Mercado Livre: ofertas via API oficial (api.mercadolibre.com).

Autenticação: a busca exige um access token. O bot gera um sozinho com o
client_id/client_secret do seu aplicativo (grant_type=client_credentials) e
renova quando expira. Crie o app em https://developers.mercadolivre.com.br/devcenter.
Se preferir, cole um token pronto em ML_ACCESS_TOKEN no .env.

O link de afiliado não vem da API: é gerado pelo Linkbuilder (ver afiliado_ml.py).
"""
import logging
import time

import requests

from ..afiliado_ml import e_link_ml, extrair_id, gerar_links_afiliado
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
        # vira True no primeiro 403 da busca: daí em diante vai direto para as alternativas
        self.busca_bloqueada = False
        self._filhas: dict[str, list[str]] = {}   # cache: categoria -> subcategorias
        self.rodizio_sub: dict[str, int] = {}     # categoria -> próxima subcategoria da vez
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

    def item(self, item_id: str) -> dict:
        return self.get(f"/items/{item_id}")

    # ── alternativas para quando /sites/{site}/search responde 403 ───
    def destaques(self, site: str, categoria: str) -> list[dict]:
        """Mais vendidos da categoria: [{"id", "type": ITEM|PRODUCT|USER_PRODUCT, "position"}]."""
        return self.get(f"/highlights/{site}/category/{categoria}").get("content") or []

    def subcategorias(self, categoria: str) -> list[str]:
        """Ids das subcategorias diretas (consulta a API uma vez por categoria)."""
        if categoria not in self._filhas:
            try:
                filhas = self.get(f"/categories/{categoria}").get("children_categories") or []
                self._filhas[categoria] = [c["id"] for c in filhas if c.get("id")]
            except ErroAPI as e:
                log.warning("Não consegui ler as subcategorias de %s: %s", categoria, e)
                self._filhas[categoria] = []
        return self._filhas[categoria]

    def itens(self, ids: list[str]) -> list[dict]:
        """Multiget de anúncios (até 20 por chamada); devolve só os que vieram com 200."""
        corpos = []
        for i in range(0, len(ids), 20):
            resp = self.get("/items", {"ids": ",".join(ids[i:i + 20])})
            corpos += [r["body"] for r in resp if r.get("code") == 200 and r.get("body")]
        return corpos

    def produto(self, produto_id: str) -> dict:
        return self.get(f"/products/{produto_id}")

    def itens_do_produto(self, produto_id: str) -> list[dict]:
        return self.get(f"/products/{produto_id}/items", {"limit": 1}).get("results") or []

    def buscar_produtos(self, site: str, q: str, limite: int = 20) -> list[dict]:
        """Busca no catálogo (produtos, não anúncios)."""
        return self.get("/products/search", {"status": "active", "site_id": site, "q": q,
                                             "limit": max(1, min(limite, 50))}).get("results") or []


_cliente: ClienteML | None = None


def cliente_padrao() -> ClienteML:
    """Cliente único enquanto o bot roda: reaproveita o token (válido por horas)
    e lembra se a busca está bloqueada, em vez de refazer tudo a cada categoria."""
    global _cliente
    if _cliente is None:
        _cliente = ClienteML.do_config()
    return _cliente


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

    return Oferta(
        plataforma="mercadolivre",
        id_produto=str(item["id"]),
        titulo=item["title"].strip(),
        url_produto=item["permalink"].split("#")[0].split("?")[0],
        preco=float(preco) if preco is not None else None,
        preco_original=float(original) if original else None,
        imagem=_imagem(item),
        extra=" · ".join(partes) or None,
    )


def produto_para_oferta(produto: dict, anuncio: dict | None = None) -> Oferta | None:
    """Produto de catálogo (+ anúncio vencedor, com o preço) -> Oferta."""
    anuncio = anuncio or produto.get("buy_box_winner") or {}
    nome = produto.get("name")
    if not (produto.get("id") and nome and anuncio.get("price") is not None):
        return None
    fotos = produto.get("pictures") or []
    url = produto.get("permalink") or f"https://www.mercadolivre.com.br/p/{produto['id']}"
    partes = []
    if (anuncio.get("shipping") or {}).get("free_shipping"):
        partes.append("🚚 Frete grátis")
    original = anuncio.get("original_price")
    return Oferta(
        plataforma="mercadolivre",
        id_produto=str(produto["id"]),
        titulo=nome.strip(),
        url_produto=url.split("#")[0].split("?")[0],
        preco=float(anuncio["price"]),
        preco_original=float(original) if original else None,
        imagem=(fotos[0].get("secure_url") or fotos[0].get("url")) if fotos else None,
        extra=" · ".join(partes) or None,
    )


def _consultas(so_categorias: dict[str, str] | None = None) -> list[tuple[str, dict]]:
    """[(rótulo, {"q": ...} ou {"categoria": ...})] a partir do config.yaml
    (ou só das categorias passadas, quando escolhidas no menu)."""
    if so_categorias:
        return [(f"categoria {nome}", {"categoria": cid}) for cid, nome in so_categorias.items()]
    fonte = config.fonte_ml
    consultas = [(f"busca '{q}'", {"q": str(q)}) for q in (fonte.get("buscas") or [])]
    consultas += [(f"categoria {nome}", {"categoria": cid}) for cid, nome in categorias().items()]
    return consultas


def categorias() -> dict[str, str]:
    cats = config.fonte_ml.get("categorias") or {}
    return {str(k): str(v) for k, v in cats.items()} if isinstance(cats, dict) \
        else {str(c): str(c) for c in cats}


def _ofertas_de_produtos(cliente: ClienteML, ids: list[str]) -> list[Oferta]:
    ofertas = []
    for pid in ids:
        try:
            produto = cliente.produto(pid)
            anuncio = produto.get("buy_box_winner")
            if not anuncio:
                anuncios = cliente.itens_do_produto(pid)
                anuncio = anuncios[0] if anuncios else None
            o = produto_para_oferta(produto, anuncio)
        except ErroAPI as e:
            log.debug("Produto %s: %s", pid, e)
            continue
        if o:
            ofertas.append(o)
    return ofertas


def fontes_da_vez(cliente: ClienteML, categoria: str, qtd: int) -> list[str]:
    """Rodízio entre a categoria e as suas subcategorias: a cada chamada, as
    próximas `qtd` da fila (a lista dos mais vendidos de cada uma é curta)."""
    nos = [categoria] + cliente.subcategorias(categoria)
    i = cliente.rodizio_sub.get(categoria, 0)
    vez = [nos[(i + k) % len(nos)] for k in range(min(max(1, qtd), len(nos)))]
    cliente.rodizio_sub[categoria] = (i + len(vez)) % len(nos)
    return vez


def _via_destaques(cliente: ClienteML, site: str, categoria: str, limite: int) -> list[Oferta]:
    """Mais vendidos das (sub)categorias da vez -> anúncios (multiget) e produtos de catálogo."""
    qtd = int(config.fonte_ml.get("subcategorias_por_busca", 2))
    ofertas: list[Oferta] = []
    for no in fontes_da_vez(cliente, categoria, qtd):
        try:
            ofertas += _destaques_de(cliente, site, no, limite)
        except ErroAPI as e:  # subcategoria sem ranking de mais vendidos
            log.debug("Mais vendidos de %s: %s", no, e)
    return ofertas


def _destaques_de(cliente: ClienteML, site: str, categoria: str, limite: int) -> list[Oferta]:
    conteudo = cliente.destaques(site, categoria)[:limite]
    ids_itens = [c["id"] for c in conteudo if c.get("type") == "ITEM"]
    ids_produtos = [c["id"] for c in conteudo if c.get("type") == "PRODUCT"]
    ofertas = [o for o in (item_para_oferta(i) for i in cliente.itens(ids_itens)) if o] \
        if ids_itens else []
    return ofertas + _ofertas_de_produtos(cliente, ids_produtos)


def _via_catalogo(cliente: ClienteML, site: str, q: str, limite: int) -> list[Oferta]:
    """Busca por palavra no catálogo -> preço do anúncio vencedor de cada produto."""
    ids = [p["id"] for p in cliente.buscar_produtos(site, q, limite) if p.get("id")]
    return _ofertas_de_produtos(cliente, ids)


def _buscar_api(cliente: ClienteML, so_categorias: dict[str, str] | None = None) -> dict[str, Oferta]:
    site = str(config.fonte_ml.get("site") or "MLB")
    limite = int(config.fonte_ml.get("limite_por_busca", 50))
    limite_alt = int(config.fonte_ml.get("limite_destaques", 20))
    consultas = _consultas(so_categorias)
    if not consultas:
        log.warning("Mercado Livre: nenhuma busca/categoria no config.yaml")
    ofertas: dict[str, Oferta] = {}
    for rotulo, kw in consultas:
        achadas: list[Oferta] = []
        try:
            if not cliente.busca_bloqueada:
                try:
                    itens = cliente.buscar(site, limite=limite, **kw)
                    achadas = [o for o in (item_para_oferta(i) for i in itens) if o]
                except ErroAPI as e:
                    if "HTTP 403" not in str(e):
                        raise
                    cliente.busca_bloqueada = True
                    log.warning("Mercado Livre: busca da API bloqueada (403) para este app — "
                                "usando mais vendidos/catálogo")
            if cliente.busca_bloqueada:
                achadas = (_via_destaques(cliente, site, kw["categoria"], limite_alt)
                           if "categoria" in kw else _via_catalogo(cliente, site, kw["q"], limite_alt))
        except ErroAPI as e:
            log.error("Mercado Livre %s: %s", rotulo, e)
            continue
        for o in achadas:
            ofertas.setdefault(o.id_produto, o)
        log.info("Mercado Livre %s: %d itens", rotulo, len(achadas))
        time.sleep(0.3)
    return ofertas


# categoria -> próxima página de mercadolivre.com.br/ofertas a ler (rodízio)
_pagina_da_vez: dict[str, int] = {}


def _via_pagina_ofertas(cats: dict[str, str]) -> list[Oferta]:
    """Página de ofertas de cada categoria (só produtos em promoção), em rodízio de
    páginas: a cada chamada lê as próximas `paginas_ofertas`, até `paginas_ofertas_max`."""
    from . import ml_pagina
    por_vez = max(1, int(config.fonte_ml.get("paginas_ofertas", 1)))
    maximo = max(por_vez, int(config.fonte_ml.get("paginas_ofertas_max", 10)))
    ofertas: list[Oferta] = []
    for cid, nome in cats.items():
        inicio = _pagina_da_vez.get(cid, 1)
        achadas = ml_pagina.buscar_ofertas({cid: nome}, por_vez, inicio,
                                           str(config.fonte_ml.get("pagina_navegador") or "auto"))
        proxima = inicio + por_vez
        # acabaram as páginas (ou chegou no máximo): volta para a primeira
        _pagina_da_vez[cid] = 1 if (not achadas or proxima > maximo) else proxima
        ofertas += achadas
    return ofertas


def buscar_ofertas(cliente: ClienteML | None = None,
                   so_categorias: dict[str, str] | None = None) -> list[Oferta]:
    """Ofertas de todas as buscas/categorias do config, ou só de so_categorias (sem repetição).

    modo (config.yaml): "auto" = mais vendidos da API + página de ofertas do ML;
    "api" = só API; "pagina" = só a página de ofertas.
    """
    modo = str(config.fonte_ml.get("modo") or "auto").lower()
    cats = so_categorias or categorias()
    ofertas: dict[str, Oferta] = {}
    if modo in ("auto", "api"):
        try:
            ofertas = _buscar_api(cliente or cliente_padrao(), so_categorias)
        except ErroAPI as e:
            log.error("Mercado Livre API: %s", e)
    if modo in ("auto", "pagina"):
        for o in _via_pagina_ofertas(cats):
            ofertas.setdefault(o.id_produto, o)
    log.info("Mercado Livre: %d ofertas coletadas", len(ofertas))
    return list(ofertas.values())


def converter(url: str, cliente: ClienteML | None = None) -> Oferta:
    """Link de produto do ML -> Oferta com dados da API + link de afiliado."""
    url = url.split("#")[0]
    if "meli.la/" in url:  # link de afiliado encurtado: expande até o produto
        try:
            url = requests.get(url, allow_redirects=True, timeout=20,
                               headers={"User-Agent": USER_AGENT}).url.split("#")[0]
        except requests.RequestException as e:
            log.warning("Não consegui expandir o link meli.la: %s", e)
    item_id = extrair_id(url)
    oferta = None
    if item_id:
        try:
            oferta = item_para_oferta((cliente or cliente_padrao()).item(item_id))
        except ErroAPI as e:
            log.warning("Não consegui ler o item %s na API: %s", item_id, e)
    if oferta is None:
        oferta = Oferta(plataforma="mercadolivre", id_produto=item_id or url[-40:],
                        titulo="Oferta Mercado Livre", url_produto=url.split("?")[0])
    gerar_links_afiliado([oferta])
    return oferta
