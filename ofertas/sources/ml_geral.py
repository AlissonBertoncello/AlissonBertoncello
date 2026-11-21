"""Ofertas gerais do Mercado Livre: tudo o que está em oferta, de qualquer categoria
(grupos com "ofertas_gerais: true").

1. Fonte principal, pela API oficial (não é barrada): o bot percorre sozinho as
   subcategorias dos departamentos de varejo do ML (moda e calçados, beleza, relógios,
   esportes, ferramentas, eletrônicos, casa…) e lê o ranking de mais vendidos e o
   catálogo de cada uma, em rodízio, sem lista fixa de marcas.
2. Ofertas achadas pela IA (sources/ia_ofertas.py), já conferidas na API do ML, entram
   no mesmo estoque (fonte "ia").
3. Opcional e desligada por padrão (pagina_ofertas: true): página geral de ofertas
   (mercadolivre.com.br/ofertas) num Chrome com perfil próprio. Nos testes o ML barrou
   todo acesso automático a ela (tela de segurança ou de verificação de conta).

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
FONTE_IA = "ia"              # estoque das ofertas achadas pela IA (vale para todo grupo de ofertas gerais)

# departamentos usados quando o grupo não escolhe (começo do nome no ML, sem acento);
# o número é o peso no rodízio (moda e calçados vendem mais: aparecem 2x)
DEPARTAMENTOS_PADRAO = (("calcados, roupas", 2), ("beleza", 1), ("joias", 1), ("esportes", 1),
                        ("ferramentas", 1), ("celulares", 1), ("eletronicos", 1),
                        ("informatica", 1), ("casa, moveis", 1), ("saude", 1))

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
_em_alta: dict[str, tuple[float, list[str]]] = {}  # categoria ("" = geral) -> (lida em, termos)
_rodizio_alta: dict[str, int] = {}       # grupo -> próximo termo em alta
_em_alta_recusada: list[str] = []        # motivo, se o ML recusou a lista (não tenta mais nesta execução)
VALIDADE_EM_ALTA_H = 6                   # termos mais buscados: relidos a cada 6 h
# termos em alta que não viram boa oferta: datas, festa, infantil, obra… (sem acento)
_TERMOS_FRACOS = ("black friday", "natal", "papai noel", "advento", "halloween", "pascoa", "carnaval",
                  "festa", "aniversario", "lembranca", "brinde", "bandeira", "bexiga", "balao",
                  "decoracao", "enfeite", "arvore", "presepio", "fantasia", "dia das maes", "dia dos pais",
                  "dia das criancas", "copa do mundo", "snoopy", "funko", "croche", "verniz", "graxa",
                  "pote misterioso", "misterioso", "kit sobrevivencia", "personalizado")


def _opcoes() -> dict:
    o = config.fonte_ml.get("ofertas_gerais") or {}
    return {"paginas_por_ciclo": int(o.get("paginas_por_ciclo", 2)),
            "atualizar_minutos": int(o.get("atualizar_minutos", 30)),
            "paginas_max": int(o.get("paginas_max", 10)),
            "janela": str(o.get("janela") or "visivel").lower(),
            "pagina_ofertas": bool(o.get("pagina_ofertas", False))}


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
    _limpar_estoque(agora)
    op = _opcoes()
    if not op["pagina_ofertas"]:  # desligada por padrão: o ML barra o acesso automático
        return
    fontes = {f for g in grupos if g.ofertas_gerais for f in fontes_do_grupo(g)}
    if not fontes or pausada():
        return
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
    _limpar_estoque(agora)
    if lidas:
        log.info("Ofertas gerais do ML: %d ofertas lidas (estoque: %d)", lidas,
                 sum(len(e) for e in _estoque.values()))


def _limpar_estoque(agora: float) -> None:
    """Tira do estoque o que foi lido há tempo demais (o preço muda)."""
    for estoque in _estoque.values():
        for k in [k for k, (_, em) in estoque.items() if agora - em > VALIDADE_ESTOQUE_H * 3600]:
            del estoque[k]


def guardar(fonte: str, ofertas: list[Oferta], agora: float | None = None) -> None:
    """Põe ofertas no estoque (usado pela IA, com fonte "ia")."""
    agora = agora or time.time()
    estoque = _estoque.setdefault(fonte, {})
    for o in ofertas:
        estoque[o.id_produto] = (o, agora)


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
    for fonte in [FONTE_IA] + fontes_do_grupo(g):
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


def _sem_acento(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def escolher_departamentos(raiz: list[dict]) -> list[str]:
    """Departamentos de varejo do ML na ordem do rodízio (com peso); sem nenhum conhecido,
    todos menos os que não são de varejo."""
    nomes = [(c["id"], _sem_acento(c.get("name", ""))) for c in raiz if c.get("id")]
    escolhidos: list[str] = []
    for inicio, peso in DEPARTAMENTOS_PADRAO:
        for cid, nome in nomes:
            if nome.startswith(inicio):
                escolhidos += [cid] * peso
                break
    if not escolhidos:
        escolhidos = [cid for cid, nome in nomes if not any(_sem_acento(x) in nome for x in _FORA)]
    # espalha as repetições (A B A C… em vez de A A B C)
    unicos = list(dict.fromkeys(escolhidos))
    extras = [c for c in unicos if escolhidos.count(c) > 1]
    ordem: list[str] = []
    for i, c in enumerate(unicos):
        ordem.append(c)
        if extras and i == len(unicos) // 2:
            ordem += extras
    return ordem


def _departamentos(g: Grupo, cliente) -> list[str]:
    if g.departamentos:
        return list(g.departamentos)
    guardado = _termos.get("_raiz2")
    if not guardado or time.time() - guardado["em"] > VALIDADE_TERMOS_DIAS * 86400:
        raiz = cliente.categorias_raiz(str(config.fonte_ml.get("site") or "MLB"))
        _termos["_raiz2"] = {"em": time.time(), "termos": escolher_departamentos(raiz)}
        _salvar_termos()
    return _termos["_raiz2"]["termos"]


def itens_do_departamento(dep: str, cliente) -> list[tuple[str, str]]:
    """Subcategorias do departamento: [(id do ranking, nome para o catálogo)].

    O ranking de mais vendidos é lido na subcategoria do 1º nível ('Calçados', 'Relógios'),
    que tem ranking; as do 2º nível ('Tênis', 'Polos', 'Mochilas') costumam não ter (404)
    e servem de nome para a busca no catálogo. A ordem alterna entre as subcategorias do
    1º nível, para variar."""
    _carregar_termos()
    guardado = _termos.get(dep)
    if guardado and guardado.get("v") == 2 and time.time() - guardado["em"] < VALIDADE_TERMOS_DIAS * 86400:
        return [tuple(x) for x in guardado["itens"]]
    grupos: list[list[tuple[str, str]]] = []
    for filha in cliente.categoria(dep).get("children_categories") or []:
        try:
            netas = cliente.categoria(filha["id"]).get("children_categories") or []
        except Exception as e:
            log.debug("Subcategorias de %s: %s", filha.get("id"), e)
            netas = []
        grupos.append([(filha["id"], n["name"]) for n in netas] or [(filha["id"], filha["name"])])
    itens = [g[i] for i in range(max((len(g) for g in grupos), default=0)) for g in grupos if i < len(g)]
    vistos, limpos = set(), []
    for cid, nome in itens:
        if nome and nome not in vistos and not nome.lower().startswith("outr"):
            vistos.add(nome)
            limpos.append((cid, nome))
    _termos[dep] = {"em": time.time(), "itens": limpos, "v": 2}
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


def _sem_ranking() -> set[str]:
    _carregar_termos()
    return set((_termos.get("_sem_ranking") or {}).get("termos") or [])


def mais_vendidos(cid: str, cliente) -> list[Oferta]:
    """Ranking de mais vendidos da subcategoria (com a posição de cada produto). Categoria
    sem ranking (404) fica anotada e não é pedida de novo por uma semana."""
    from .mercadolivre import _destaques_de
    # Fonte adicional, desligada por padrão; mantém integralmente o fluxo anterior.
    if config.fonte_ml.get("ranking_adicional", False):
        try:
            from .ml_ranking_adicional import descobrir
            extras = descobrir(cliente, str(config.fonte_ml.get("site") or "MLB"), cid,
                               int(config.fonte_ml.get("limite_destaques", 20)))
        except Exception as exc:
            log.warning("Ranking adicional indisponível em %s: %s", cid, exc)
            extras = []
    else:
        extras = []
    if cid in _sem_ranking():
        return []
    site = str(config.fonte_ml.get("site") or "MLB")
    try:
        atuais = _destaques_de(cliente, site, cid, int(config.fonte_ml.get("limite_destaques", 20)))
        ids = {o.id_produto for o in atuais}
        return atuais + [o for o in extras if o.id_produto not in ids]
    except Exception as e:
        if "HTTP 404" not in str(e):
            raise
        guardado = _termos.get("_sem_ranking")
        if not guardado or time.time() - guardado["em"] > VALIDADE_TERMOS_DIAS * 86400:
            guardado = _termos["_sem_ranking"] = {"em": time.time(), "termos": []}
        guardado["termos"].append(cid)
        _salvar_termos()
        return []


def catalogo(termo: str, cliente, limite: int = 10) -> list[Oferta]:
    """Produtos do catálogo do ML para o termo (qualquer marca), com a posição na busca."""
    from .mercadolivre import _via_catalogo
    site = str(config.fonte_ml.get("site") or "MLB")
    achadas = _via_catalogo(cliente, site, termo, limite)
    for i, o in enumerate(achadas, 1):
        o.posicao = i
    return achadas


# ── 3. em alta: termos mais buscados no ML agora -> catálogo ──────────

def _ler_em_alta(cid: str, cliente) -> list[str]:
    site = str(config.fonte_ml.get("site") or "MLB")
    caminho = f"/trends/{site}/{cid}" if cid else f"/trends/{site}"
    dados = cliente.get(caminho)
    itens = dados if isinstance(dados, list) else (dados or {}).get("results") or []
    return [str(x.get("keyword") or "").strip() for x in itens if isinstance(x, dict) and x.get("keyword")]


def termos_em_alta(g: Grupo, cliente, agora: float | None = None) -> list[str]:
    """Termos mais buscados agora no ML: os de cada departamento do grupo, intercalados,
    e os gerais (relidos a cada 6 h). Vazio se o ML não liberar a lista."""
    if _em_alta_recusada:
        return []
    agora = agora or time.time()
    listas = []
    # só os departamentos de varejo do grupo: a lista geral mistura datas, games, festa…
    for cid in _departamentos_unicos(g, cliente):
        lida, termos = _em_alta.get(cid, (0.0, []))
        if agora - lida > VALIDADE_EM_ALTA_H * 3600:
            try:
                termos = _ler_em_alta(cid, cliente)
            except Exception as e:
                if "HTTP 403" in str(e) or "HTTP 401" in str(e):
                    _em_alta_recusada.append(str(e)[:120])
                    log.warning("Mercado Livre: a lista de mais buscados (em alta) não está liberada "
                                "para este app — seguindo sem ela")
                    return []
                log.debug("Em alta %s: %s", cid or "geral", e)
                termos = termos or []
            _em_alta[cid] = (agora, termos)
        listas.append(termos)
    vistos, saida = set(), []
    for i in range(max((len(x) for x in listas), default=0)):
        for termos in listas:
            if i < len(termos) and termos[i].lower() not in vistos:
                vistos.add(termos[i].lower())
                if termo_bom(termos[i], g):
                    saida.append(termos[i])
    return saida


def termo_bom(termo: str, g: Grupo) -> bool:
    """Termo em alta que vale procurar: duas palavras ou mais (ou uma marca conhecida),
    sem data comemorativa/festa/infantil e sem palavra bloqueada do grupo ou geral."""
    from ..pipeline import tem_palavra_bloqueada
    from ..qualidade import e_marca
    t = _sem_acento(termo).strip()
    if not t:
        return False
    if len(t.split()) < 2 and not e_marca(t):
        return False
    if any(f in t for f in _TERMOS_FRACOS):
        return False
    return not tem_palavra_bloqueada(termo, g.bloquear)


def _departamentos_unicos(g: Grupo, cliente) -> list[str]:
    try:
        return list(dict.fromkeys(_departamentos(g, cliente)))
    except Exception as e:
        log.debug("Departamentos: %s", e)
        return []


def em_alta_da_vez(g: Grupo, cliente, qtd: int = 2) -> list[str]:
    """Próximos termos em alta do grupo, em rodízio."""
    termos = termos_em_alta(g, cliente)
    if not termos:
        return []
    i = _rodizio_alta.get(g.chave, 0)
    _rodizio_alta[g.chave] = i + qtd
    return [termos[(i + k) % len(termos)] for k in range(min(qtd, len(termos)))]
