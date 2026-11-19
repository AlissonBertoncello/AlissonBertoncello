"""Ofertas gerais do Mercado Livre: tudo o que está em oferta, de qualquer categoria
(grupos com "ofertas_gerais: true").

1. Fonte principal, pela API oficial (não é barrada): o bot percorre sozinho as
   subcategorias de cada departamento do ML (tênis, polos, mochilas, relógios,
   ferramentas…) e lê o ranking de mais vendidos e o catálogo de cada uma, em rodízio,
   sem lista fixa de categorias nem de marcas.
2. Bônus: página geral de ofertas (mercadolivre.com.br/ofertas, ou a de cada
   departamento do grupo), poucas páginas por ciclo, num Chrome de verdade com a janela
   fora da tela e um perfil próprio, sem login. Se ela vier barrada ou vazia, fica
   pausada por algumas horas (a cópia vai para data/ml_geral_debug.html).

Ajustes em fontes.mercadolivre.ofertas_gerais no config.yaml (todos opcionais).
"""
import json
import logging
import time
from dataclasses import replace

from ..config import DATA_DIR, config
from ..models import Grupo, Oferta
from . import ml_pagina

log = logging.getLogger("ofertas.ml")

PERFIL_DIR = DATA_DIR / "ml_ofertas_profile"   # perfil separado, sem login
ARQ_TERMOS = DATA_DIR / "ml_termos_catalogo.json"
VALIDADE_ESTOQUE_H = 12      # oferta lida há mais tempo que isso sai do estoque (o preço muda)
VALIDADE_TERMOS_DIAS = 7     # nomes das subcategorias: relidos uma vez por semana
PAUSA_BLOQUEIO_H = 3
TERMOS_POR_CICLO = 3         # buscas no catálogo por grupo e ciclo, antes de desistir

# departamentos que não são de varejo (ficam fora quando o grupo não escolhe departamentos)
_FORA = ("imóveis", "imoveis", "carros, motos", "serviços", "servicos", "ingressos",
         "mais categorias", "agro", "indústria", "industria", "antiguidades")

_estoque: dict[str, dict[str, tuple[Oferta, float]]] = {}  # fonte ("" = geral) -> id -> (oferta, lida em)
_lida_em: dict[str, float] = {}          # fonte -> última leitura
_pagina_da_vez: dict[str, int] = {}      # fonte -> próxima página
_pausada_ate = 0.0
_termos: dict[str, dict] = {}            # departamento -> {"em": ts, "termos": [...]}
_rodizio_dep: dict[str, int] = {}        # grupo -> próximo departamento
_rodizio_termo: dict[tuple[str, str], int] = {}  # (grupo, departamento) -> próximo termo


def _opcoes() -> dict:
    o = config.fonte_ml.get("ofertas_gerais") or {}
    return {"paginas_por_ciclo": int(o.get("paginas_por_ciclo", 2)),
            "atualizar_minutos": int(o.get("atualizar_minutos", 30)),
            "paginas_max": int(o.get("paginas_max", 10)),
            "janela": str(o.get("janela") or "visivel").lower()}


def fontes_do_grupo(g: Grupo) -> list[str]:
    """Páginas de ofertas que interessam ao grupo: as dos departamentos dele, ou a geral."""
    return list(g.departamentos) or [""]


def pausada() -> bool:
    return time.time() < _pausada_ate


# ── 1. página de ofertas ─────────────────────────────────────────────

def _chrome_ler(urls: list[str]) -> dict[str, str]:
    """Abre as páginas num Chrome com perfil próprio (janela fora da tela, se der)."""
    from playwright.sync_api import sync_playwright

    from ..afiliado_ml import _abrir_contexto

    PERFIL_DIR.mkdir(parents=True, exist_ok=True)
    visivel = _opcoes()["janela"] != "oculta"
    with sync_playwright() as pw:
        try:
            ctx = _abrir_contexto(pw, PERFIL_DIR, visivel=visivel)
        except Exception as e:
            if not visivel:
                raise
            log.warning("Ofertas gerais: não deu para abrir o Chrome com janela (%s) — usando o oculto",
                        str(e).splitlines()[0][:120])
            ctx = _abrir_contexto(pw, PERFIL_DIR, visivel=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return ml_pagina.ler_paginas(page, urls, pausa_s=(3, 7))
        finally:
            ctx.close()


def atualizar(grupos: list[Grupo], agora: float | None = None) -> None:
    """Lê as próximas páginas de ofertas das fontes que estão há mais tempo sem leitura
    (no máximo `paginas_por_ciclo` páginas por ciclo, somando todas as fontes)."""
    global _pausada_ate
    agora = agora or time.time()
    fontes = {f for g in grupos if g.ofertas_gerais for f in fontes_do_grupo(g)}
    if not fontes or pausada():
        return
    op = _opcoes()
    vencidas = sorted((f for f in fontes if agora - _lida_em.get(f, 0) >= op["atualizar_minutos"] * 60),
                      key=lambda f: _lida_em.get(f, 0))
    if not vencidas:
        return
    alvos: list[tuple[str, str]] = []  # (fonte, url)
    for i in range(op["paginas_por_ciclo"]):
        fonte = vencidas[i % len(vencidas)]
        pagina = _pagina_da_vez.get(fonte, 1) + sum(1 for f, _ in alvos if f == fonte)
        alvos.append((fonte, ml_pagina._url(fonte, pagina)))
    try:
        htmls = _chrome_ler([u for _, u in alvos])
    except Exception as e:
        log.error("Ofertas gerais: não consegui abrir o Chrome: %s", e)
        return
    lidas = 0
    for fonte, url in alvos:
        html = htmls.get(url)
        if ml_pagina.e_bloqueio(html):
            _pausada_ate = agora + PAUSA_BLOQUEIO_H * 3600
            log.warning("Ofertas gerais: o Mercado Livre barrou a página de ofertas — pausada por %d h; "
                        "os grupos seguem com os mais vendidos e o catálogo do ML", PAUSA_BLOQUEIO_H)
            break
        if html is None:
            continue
        achadas = ml_pagina.parse_pagina(html)
        if not achadas and pagina_de(url) == 1:
            # a página abriu, mas sem nenhuma oferta reconhecível (layout diferente, tela de CEP…)
            _salvar_debug(html)
            _pausada_ate = agora + PAUSA_BLOQUEIO_H * 3600
            log.warning("Ofertas gerais: a página de ofertas abriu sem ofertas reconhecíveis (título: %r, "
                        "%d bytes) — pausada por %d h; cópia em data/ml_geral_debug.html. Os grupos "
                        "seguem com os mais vendidos e o catálogo do ML", ml_pagina._titulo(html),
                        len(html), PAUSA_BLOQUEIO_H)
            break
        estoque = _estoque.setdefault(fonte, {})
        for o in achadas:
            estoque[o.id_produto] = (o, agora)
        lidas += len(achadas)
        _lida_em[fonte] = agora
        proxima = _pagina_da_vez.get(fonte, 1) + 1
        _pagina_da_vez[fonte] = 1 if (not achadas or proxima > op["paginas_max"]) else proxima
    for estoque in _estoque.values():  # tira o que está velho demais
        for k in [k for k, (_, em) in estoque.items() if agora - em > VALIDADE_ESTOQUE_H * 3600]:
            del estoque[k]
    if lidas:
        log.info("Ofertas gerais do ML: %d ofertas lidas (estoque: %d)", lidas,
                 sum(len(e) for e in _estoque.values()))


def pagina_de(url: str) -> int:
    import re
    m = re.search(r"[?&]page=(\d+)", url)
    return int(m.group(1)) if m else 1


def _salvar_debug(html: str) -> None:
    try:
        (DATA_DIR / "ml_geral_debug.html").write_text(html, encoding="utf-8")
    except OSError:
        pass


def ofertas_para(g: Grupo) -> list[Oferta]:
    """Cópias das ofertas do estoque que interessam ao grupo (cada grupo gera o próprio link)."""
    vistas, saida = set(), []
    for fonte in fontes_do_grupo(g):
        for o, _ in (_estoque.get(fonte) or {}).values():
            if o.id_produto not in vistas:
                vistas.add(o.id_produto)
                saida.append(replace(o, url_afiliado=""))
    return saida


# ── 2. reserva: catálogo do ML pelos nomes das subcategorias ─────────

def _carregar_termos() -> None:
    if _termos or not ARQ_TERMOS.exists():
        return
    try:
        _termos.update(json.loads(ARQ_TERMOS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _salvar_termos() -> None:
    try:
        ARQ_TERMOS.write_text(json.dumps(_termos, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _departamentos(g: Grupo, cliente) -> list[str]:
    if g.departamentos:
        return list(g.departamentos)
    if "_raiz" not in _termos or time.time() - _termos["_raiz"]["em"] > VALIDADE_TERMOS_DIAS * 86400:
        raiz = cliente.categorias_raiz(str(config.fonte_ml.get("site") or "MLB"))
        _termos["_raiz"] = {"em": time.time(),
                            "termos": [c["id"] for c in raiz
                                       if not any(x in c.get("name", "").lower() for x in _FORA)]}
        _salvar_termos()
    return _termos["_raiz"]["termos"]


def itens_do_departamento(dep: str, cliente) -> list[tuple[str, str]]:
    """Subcategorias (2 níveis) do departamento: [(id, nome)] — 'Tênis', 'Polos', 'Mochilas'…"""
    _carregar_termos()
    guardado = _termos.get(dep)
    if guardado and "itens" in guardado and time.time() - guardado["em"] < VALIDADE_TERMOS_DIAS * 86400:
        return [tuple(x) for x in guardado["itens"]]
    itens: list[tuple[str, str]] = []
    for filha in cliente.categoria(dep).get("children_categories") or []:
        try:
            netas = cliente.categoria(filha["id"]).get("children_categories") or []
        except Exception as e:
            log.debug("Subcategorias de %s: %s", filha.get("id"), e)
            netas = []
        itens += [(n["id"], n["name"]) for n in netas] or [(filha["id"], filha["name"])]
    vistos, limpos = set(), []
    for cid, nome in itens:
        if nome and nome not in vistos and not nome.lower().startswith("outr"):
            vistos.add(nome)
            limpos.append((cid, nome))
    _termos[dep] = {"em": time.time(), "itens": limpos}
    _salvar_termos()
    return limpos


def termos_do_departamento(dep: str, cliente) -> list[str]:
    return [nome for _, nome in itens_do_departamento(dep, cliente)]


def da_vez(g: Grupo, cliente, qtd: int = TERMOS_POR_CICLO) -> list[tuple[str, str]]:
    """Próximas subcategorias do grupo [(id, nome)], um departamento de cada vez (variedade)."""
    _carregar_termos()
    deps = _departamentos(g, cliente)
    escolhidos: list[tuple[str, str]] = []
    for _ in range(len(deps) * 2):
        if len(escolhidos) >= qtd or not deps:
            break
        i = _rodizio_dep.get(g.chave, 0) % len(deps)
        _rodizio_dep[g.chave] = i + 1
        try:
            itens = itens_do_departamento(deps[i], cliente)
        except Exception as e:
            log.warning("Mercado Livre: não consegui ler o departamento %s: %s", deps[i], e)
            continue
        if not itens:
            continue
        j = _rodizio_termo.get((g.chave, deps[i]), 0) % len(itens)
        _rodizio_termo[(g.chave, deps[i])] = j + 1
        escolhidos.append(itens[j])
    return escolhidos


def termos_da_vez(g: Grupo, cliente, qtd: int = TERMOS_POR_CICLO) -> list[str]:
    return [nome for _, nome in da_vez(g, cliente, qtd)]


def mais_vendidos(cid: str, cliente) -> list[Oferta]:
    """Ranking de mais vendidos da subcategoria (com a posição de cada produto)."""
    from .mercadolivre import _destaques_de
    site = str(config.fonte_ml.get("site") or "MLB")
    return _destaques_de(cliente, site, cid, int(config.fonte_ml.get("limite_destaques", 20)))


def catalogo(termo: str, cliente, limite: int = 10) -> list[Oferta]:
    """Produtos do catálogo do ML para o termo (qualquer marca), com a posição na busca."""
    from .mercadolivre import _via_catalogo
    site = str(config.fonte_ml.get("site") or "MLB")
    achadas = _via_catalogo(cliente, site, termo, limite)
    for i, o in enumerate(achadas, 1):
        o.posicao = i
    return achadas
