"""Busca crua no Mercado Livre, do zero: sem filtro, sem nota, sem grupo, sem envio.

    uv run python -m ofertas buscar-ml        (ou BUSCAR_ML.bat)

Tenta todos os caminhos e mostra os produtos que cada um devolve (título, preço, link):
  1. Página de ofertas (Ofertas do dia) no Chrome logado no afiliado — geral e de moda
  2. API: ranking de mais vendidos -> preço por TODOS os caminhos (anúncio, produto,
     anúncios do produto, user-product), anotando o HTTP de cada um
  3. API: busca no catálogo por palavra

Guarda tudo em data/busca_ml/: resultado.txt, as páginas (HTML) e as respostas cruas da
API (JSON), para descobrir exatamente onde o produto ou o preço some. Não envia nada.
"""
import json
import logging
import time

from .config import DATA_DIR
from .sources import ml_pagina
from .sources.mercadolivre import ClienteML, ErroAPI

PASTA = DATA_DIR / "busca_ml"
CATEGORIAS = {"MLB1430": "Calçados, Roupas e Bolsas", "MLB1246": "Beleza", "MLB1000": "Eletrônicos",
              "MLB1648": "Informática", "MLB263532": "Ferramentas"}
PALAVRAS = ["tênis nike", "perfume masculino", "relógio casio"]
POR_CAMINHO = 5  # produtos consultados por categoria em cada caminho da API

_linhas: list[str] = []


def _p(t: str = "") -> None:
    print(t)
    _linhas.append(t)


def _guardar(nome: str, dados) -> None:
    try:
        texto = dados if isinstance(dados, str) else json.dumps(dados, ensure_ascii=False, indent=1)
        (PASTA / nome).write_text(texto, encoding="utf-8")
    except OSError:
        pass


def _produto(titulo, preco, original, link) -> str:
    p = f"R$ {preco:.2f}" if isinstance(preco, (int, float)) else "SEM PREÇO"
    o = f" (de R$ {original:.2f})" if isinstance(original, (int, float)) and original else ""
    return f"     • {str(titulo)[:70]} — {p}{o}\n       {link}"


# ── 1. página de ofertas ─────────────────────────────────────────────

def pagina_de_ofertas() -> int:
    urls = [ml_pagina._url("", 1), ml_pagina._url("", 2), ml_pagina._url("MLB1430", 1)]
    _p("\n══ 1. Página de ofertas no Chrome logado (Ofertas do dia)")
    try:
        htmls = ml_pagina._html_navegador(urls)
    except Exception as e:
        _p(f"   ❌ não abriu o Chrome: {str(e).splitlines()[0][:200]}")
        return 0
    total = 0
    for i, url in enumerate(urls, 1):
        html = htmls.get(url)
        if html is None:
            _p(f"   ❌ {url}: não carregou")
            continue
        _guardar(f"pagina_{i}.html", html)
        achadas = ml_pagina.parse_pagina(html)
        barrada = ml_pagina.e_bloqueio(html)
        _p(f"\n   {'✅' if achadas else '❌'} {url}: {len(achadas)} produtos"
           + (" — BARRADA pelo ML" if barrada else "") + f" (título da página: {ml_pagina._titulo(html)!r})")
        for o in achadas[:8]:
            _p(_produto(o.titulo, o.preco, o.preco_original, o.url_produto))
        total += len(achadas)
    return total


# ── 2. API: ranking -> preço por todos os caminhos ───────────────────

def _get(c: ClienteML, caminho: str, params: dict | None = None):
    """(dados, erro): nunca levanta exceção."""
    try:
        return c.get(caminho, params), None
    except ErroAPI as e:
        return None, str(e)[:160]
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:140]}"


def _preco_do_anuncio(a: dict) -> tuple:
    return a.get("price"), a.get("original_price")


def ranking(c: ClienteML) -> int:
    _p("\n══ 2. API: ranking de mais vendidos -> preço")
    total = 0
    for cid, nome in CATEGORIAS.items():
        dados, erro = _get(c, f"/highlights/MLB/category/{cid}")
        if erro:
            _p(f"\n   ❌ {nome} ({cid}) ranking: {erro}")
            continue
        _guardar(f"api_ranking_{cid}.json", dados)
        conteudo = (dados or {}).get("content") or []
        tipos: dict[str, list[str]] = {}
        for x in conteudo:
            tipos.setdefault(str(x.get("type")), []).append(str(x.get("id")))
        _p(f"\n   {nome} ({cid}): {len(conteudo)} no ranking — "
           + ", ".join(f"{t}: {len(v)}" for t, v in tipos.items()))

        # ITEM: anúncios (multiget)
        ids = tipos.get("ITEM", [])[:POR_CAMINHO]
        if ids:
            resp, erro = _get(c, "/items", {"ids": ",".join(ids)})
            if erro:
                _p(f"     ITEM /items: ❌ {erro}")
            else:
                _guardar(f"api_items_{cid}.json", resp)
                codigos = [r.get("code") for r in resp or []]
                _p(f"     ITEM /items: códigos {codigos}")
                for r in resp or []:
                    b = r.get("body") or {}
                    if r.get("code") == 200 and b.get("title"):
                        total += 1
                        _p(_produto(b["title"], *_preco_do_anuncio(b), b.get("permalink")))

        # PRODUCT: ficha do produto, vencedor e anúncios do produto
        for i, pid in enumerate(tipos.get("PRODUCT", [])[:POR_CAMINHO]):
            prod, erro = _get(c, f"/products/{pid}")
            if erro:
                _p(f"     PRODUCT {pid}: ❌ {erro}")
                continue
            if i == 0:
                _guardar(f"api_produto_{cid}.json", prod)
            nome_p = prod.get("name") or "?"
            vencedor = prod.get("buy_box_winner") or {}
            preco, original = _preco_do_anuncio(vencedor)
            como = "buy_box_winner"
            if preco is None:
                anuncios, erro2 = _get(c, f"/products/{pid}/items", {"limit": 5})
                if i == 0 and anuncios is not None:
                    _guardar(f"api_produto_items_{cid}.json", anuncios)
                res = (anuncios or {}).get("results") or []
                if res:
                    preco, original = _preco_do_anuncio(res[0])
                    como = "/products/{id}/items"
                else:
                    como = f"/products/{{id}}/items: {'❌ ' + erro2 if erro2 else 'vazio'}"
            link = prod.get("permalink") or f"https://www.mercadolivre.com.br/p/{pid}"
            _p(f"     PRODUCT {pid} (preço via {como}):")
            _p(_produto(nome_p, preco, original, link))
            total += preco is not None

        # USER_PRODUCT: produto do vendedor (formato novo do ML)
        for i, uid in enumerate(tipos.get("USER_PRODUCT", [])[:POR_CAMINHO]):
            up, erro = _get(c, f"/user-products/{uid}")
            if i == 0:
                _guardar(f"api_user_product_{cid}.json", up if up is not None else {"erro": erro})
            if erro:
                _p(f"     USER_PRODUCT {uid}: ❌ {erro}")
                continue
            titulo = up.get("name") or up.get("title") or "?"
            preco = original = None
            itens, erro2 = _get(c, f"/user-products/{uid}/items")
            if i == 0 and itens is not None:
                _guardar(f"api_user_product_items_{cid}.json", itens)
            ids_itens = [str(x.get("id") if isinstance(x, dict) else x)
                         for x in ((itens or {}).get("results") or [])][:3]
            if ids_itens:
                resp, _ = _get(c, "/items", {"ids": ",".join(ids_itens)})
                corpo = next((r.get("body") for r in resp or [] if r.get("code") == 200), None) or {}
                preco, original = _preco_do_anuncio(corpo)
            _p(f"     USER_PRODUCT {uid} (anúncios: {ids_itens or ('❌ ' + erro2 if erro2 else 'nenhum')}):")
            _p(_produto(titulo, preco, original, f"https://www.mercadolivre.com.br/up/{uid}"))
            total += preco is not None
        time.sleep(0.3)
    return total


# ── 3. API: catálogo por palavra ─────────────────────────────────────

def catalogo(c: ClienteML) -> int:
    _p("\n══ 3. API: busca no catálogo por palavra")
    total = 0
    for q in PALAVRAS:
        dados, erro = _get(c, "/products/search", {"status": "active", "site_id": "MLB", "q": q, "limit": 10})
        if erro:
            _p(f"\n   ❌ '{q}': {erro}")
            continue
        _guardar(f"api_catalogo_{q.replace(' ', '_')}.json", dados)
        res = (dados or {}).get("results") or []
        _p(f"\n   '{q}': {len(res)} produtos")
        for r in res[:POR_CAMINHO]:
            preco = original = None
            anuncios, erro2 = _get(c, f"/products/{r.get('id')}/items", {"limit": 3})
            itens = (anuncios or {}).get("results") or []
            if itens:
                preco, original = _preco_do_anuncio(itens[0])
            else:
                vencedor = (r.get("buy_box_winner") or {})
                preco, original = _preco_do_anuncio(vencedor)
            _p(_produto(r.get("name"), preco, original, f"https://www.mercadolivre.com.br/p/{r.get('id')}")
               + ("" if preco is not None else f"\n       (anúncios do produto: {'❌ ' + erro2 if erro2 else 'vazio'})"))
            total += preco is not None
    return total


def rodar() -> None:
    log = logging.getLogger("ofertas")
    nivel = log.level
    log.setLevel(logging.WARNING)
    try:
        PASTA.mkdir(parents=True, exist_ok=True)
        _linhas.clear()
        _p("Busca crua no Mercado Livre — sem filtro, nada é enviado aos grupos")
        _p(time.strftime("%d/%m/%Y %H:%M"))
        res = {"página de ofertas": pagina_de_ofertas()}
        c = ClienteML.do_config()
        try:
            c.token()
            res["API ranking (com preço)"] = ranking(c)
            res["API catálogo (com preço)"] = catalogo(c)
        except Exception as e:
            _p(f"\n❌ API do ML: {str(e)[:200]}")
        _p("\n══ Resumo — produtos encontrados com preço:")
        for k, v in res.items():
            _p(f"   {'✅' if v else '❌'} {k}: {v}")
        (PASTA / "resultado.txt").write_text("\n".join(_linhas) + "\n", encoding="utf-8")
        print(f"\nTudo salvo em {PASTA} — mande o resultado.txt (e, se puder, a pasta inteira zipada).")
    finally:
        log.setLevel(nivel)
