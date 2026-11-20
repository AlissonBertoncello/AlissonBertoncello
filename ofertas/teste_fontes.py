"""Testa, no notebook, de onde o bot consegue trazer ofertas (não envia nada aos grupos).

    uv run python -m ofertas testar-fontes        (ou TESTAR_FONTES.bat)

A. Mercado Livre pela API: mais vendidos e catálogo das subcategorias, automático
B. Shopee: lista de mais vendidos sem palavra-chave (e uma busca por palavra, para comparar)
D1. Busca completa da API do ML com a chave do app (hoje responde 403)
G. Em alta no ML: termos mais buscados agora (lista oficial, grátis) procurados no catálogo
H. Moda no grupo de ofertas gerais: rankings das categorias de moda do grupo, com os filtros
   e a nota de qualidade — mostra os 10 que o bot mandaria e o que foi cortado (e por quê)
F. IA (ChatGPT) pesquisando ofertas, cada uma conferida na API do ML — só com a IA ligada
   no painel, porque é paga (o custo aparece no resultado)

(A página de ofertas do ML não é mais testada: nos testes de 19/11 ela barrou todo acesso
automático, até com login.) O resultado fica em data/teste_fontes/resultado.txt (sem
senhas nem dados da conta).
"""
import logging
import time

from .config import DATA_DIR, config
from .models import Grupo, Oferta

PASTA = DATA_DIR / "teste_fontes"
_linhas: list[str] = []


def _p(texto: str = "") -> None:
    print(texto)
    _linhas.append(texto)


def _resumo(ofertas: list[Oferta]) -> str:
    minimo = config.desconto_minimo or 10
    boas = [o for o in ofertas if (o.desconto or 0) >= minimo]
    texto = f"{len(ofertas)} produtos, {len(boas)} com desconto de {minimo}% ou mais"
    exemplos = sorted(boas or ofertas, key=lambda o: -(o.desconto or 0))[:3]
    for o in exemplos:
        preco = f"R$ {o.preco:.2f}" if o.preco else "sem preço"
        texto += f"\n        • {o.titulo[:60]} — {preco}" + (f" (-{o.desconto}%)" if o.desconto else "")
    return texto


def _teste(nome: str, funcao) -> bool:
    _p(f"\n── {nome}")
    inicio = time.monotonic()
    try:
        ok = funcao()
    except Exception as e:
        _p(f"   ❌ erro: {str(e).splitlines()[0][:200]}")
        ok = False
    _p(f"   ({time.monotonic() - inicio:.0f} s)")
    return bool(ok)


def _a_mercado_livre() -> bool:
    from .sources import ml_geral
    from .sources.mercadolivre import cliente_padrao
    cliente = cliente_padrao()
    vez = ml_geral.da_vez(Grupo("teste_fontes", "Teste", ofertas_gerais=True), cliente, 3)
    if not vez:
        _p("   ❌ não consegui ler os departamentos do ML")
        return False
    total = 0
    for cid, nome in vez:
        for rotulo, buscar in (("mais vendidos", lambda: ml_geral.mais_vendidos(cid, cliente)),
                               ("catálogo", lambda: ml_geral.catalogo(nome, cliente))):
            try:
                achadas = buscar()
            except Exception as e:
                _p(f"   ❌ {nome} ({rotulo}): {str(e)[:120]}")
                continue
            total += len(achadas)
            _p(f"   {'✅' if achadas else '⚪'} {nome} ({rotulo}): {_resumo(achadas)}")
    return total > 0


def _b_shopee() -> bool:
    from .sources import shopee
    if not shopee.tem_credenciais():
        _p("   ⚪ sem SHOPEE_APP_ID/SHOPEE_APP_SECRET no .env")
        return False
    ok = False
    for rotulo, buscar in (("lista mais vendidos (listType 2)", lambda: shopee.mais_vendidos(1, lista=2)),
                           ("lista maior comissão (listType 1)", lambda: shopee.mais_vendidos(1, lista=1)),
                           ("busca por palavra 'tênis' (comparação)", lambda: shopee.buscar("tênis"))):
        try:
            achadas = buscar()
            ok = ok or bool(achadas)
            _p(f"   {'✅' if achadas else '⚪'} {rotulo}: {_resumo(achadas)}")
        except Exception as e:
            _p(f"   ❌ {rotulo}: {str(e)[:200]}")
    return ok


def _g_em_alta() -> bool:
    """Termos mais buscados agora no ML (lista oficial, grátis) procurados no catálogo."""
    from .sources import ml_geral
    from .sources.mercadolivre import cliente_padrao
    cliente = cliente_padrao()
    g = Grupo("teste_fontes", "Teste", ofertas_gerais=True)
    try:
        gerais = ml_geral._ler_em_alta("", cliente)
        _p(f"   {'✅' if gerais else '⚪'} mais buscados no geral: {len(gerais)} termos — {', '.join(gerais[:10])}")
    except Exception as e:
        _p(f"   ❌ mais buscados no geral: {str(e)[:160]}")
        gerais = []
    deps = list(dict.fromkeys(ml_geral._departamentos(g, cliente)))[:4]
    por_dep = 0
    for cid in deps:
        try:
            termos = ml_geral._ler_em_alta(cid, cliente)
            por_dep += len(termos)
            _p(f"   {'✅' if termos else '⚪'} mais buscados em {cid}: {len(termos)} termos — {', '.join(termos[:6])}")
        except Exception as e:
            _p(f"   ❌ mais buscados em {cid}: {str(e)[:160]}")
    termos = ml_geral.termos_em_alta(g, cliente)
    total = 0
    for termo in termos[:4]:
        try:
            achadas = ml_geral.catalogo(termo, cliente)
        except Exception as e:
            _p(f"   ❌ catálogo '{termo}': {str(e)[:120]}")
            continue
        total += len(achadas)
        _p(f"   {'✅' if achadas else '⚪'} catálogo '{termo}': {_resumo(achadas)}")
    return total > 0


# categorias de moda (pelo nome): roupa, calçado e acessório
_RE_MODA = r"t[êe]nis|cal[çc]ad|sand[áa]li|chinel|bota|sapat|camis|camiset|regata|blus|cal[çc]a|bermud|short|" \
           r"agasalh|moletom|jaquet|vestid|roupa|moda|polo|meia|bon[ée]|rel[óo]gio|bolsa|mochila|[óo]culos|cinto|carteira"


def _grupo_do_teste() -> Grupo:
    """O primeiro grupo de ofertas gerais do config (o Clube), ou um grupo de exemplo."""
    return next((g for g in config.grupos if g.ofertas_gerais), None) or \
        Grupo("teste_fontes", "Teste", ofertas_gerais=True, desconto_minimo=25, preco_minimo=25)


def _categorias_de_moda(g: Grupo, cliente) -> list[tuple[str, str]]:
    import re
    cats = [(cid, nome) for cid, nome in g.categorias.items() if re.search(_RE_MODA, nome, re.I)]
    if cats:
        return cats
    from .sources import ml_geral  # sem categorias de moda no grupo: as do departamento de moda do ML
    raiz = cliente.categorias_raiz(str(config.fonte_ml.get("site") or "MLB"))
    dep = next((c["id"] for c in raiz if ml_geral._sem_acento(c.get("name", "")).startswith("calcados, roupas")), None)
    if not dep:
        return []
    return [(c["id"], c["name"]) for c in cliente.categoria(dep).get("children_categories") or []][:8]


def _h_moda() -> bool:
    """O que o bot mandaria de moda no grupo de ofertas gerais: rankings das categorias de moda
    (ou o catálogo pelo nome, se a categoria não tiver ranking), com os filtros e a nota de
    qualidade do grupo. Não envia nada."""
    import re
    from collections import Counter

    from . import pipeline, qualidade
    from .sources import ml_geral
    from .sources.mercadolivre import cliente_padrao
    cliente = cliente_padrao()
    g = _grupo_do_teste()
    _p(f"   Grupo: {g.nome} · desconto mínimo {g.desconto_minimo if g.desconto_minimo is not None else config.desconto_minimo}% "
       f"· preço mínimo R$ {g.preco_minimo if g.preco_minimo is not None else config.preco_minimo:.0f}")
    bloqueadas = [*config.palavras_bloqueadas, *g.bloquear]
    _p(f"   Palavras bloqueadas (geral + grupo): {', '.join(bloqueadas) or 'nenhuma'}")
    cats = _categorias_de_moda(g, cliente)
    if not cats:
        _p("   ❌ não achei categorias de moda")
        return False
    todas: list[Oferta] = []
    for cid, nome in cats:
        try:
            achadas = ml_geral.mais_vendidos(cid, cliente)
            origem = "ranking"
            if not achadas:
                achadas, origem = ml_geral.catalogo(nome, cliente, limite=30), "catálogo"
        except Exception as e:
            _p(f"   ❌ {nome}: {str(e)[:120]}")
            continue
        boas = [o for o in achadas if (o.desconto or 0) >= 25]
        _p(f"   {'✅' if boas else '⚪'} {nome} ({origem}): {len(achadas)} produtos, {len(boas)} com 25% ou mais")
        todas += achadas
    motivos = Counter()
    passam = pipeline.filtrar_do_grupo(g, todas, motivos)
    palavras = Counter()
    for o in todas:
        for b in bloqueadas:
            if b and re.search(rf"(?<!\w){re.escape(b.lower())}(?!\w)", o.titulo.lower()):
                palavras[b] += 1
    _p(f"\n   Total: {len(todas)} produtos de moda · {len(passam)} passam nos filtros do grupo")
    if motivos:
        _p("   Cortados: " + ", ".join(f"{n} {m}" for m, n in motivos.most_common()))
    if palavras:
        _p("   Palavras bloqueadas que mais cortaram: " + ", ".join(f"{w} ({n})" for w, n in palavras.most_common(8)))
    top = pipeline.escolher(passam, 10, por_nota=True)
    if top:
        _p("\n   Os 10 que o bot mandaria primeiro (pela nota):")
    for o in top:
        marca = qualidade.marca_boa(o)
        _p(f"     {qualidade.nota(o):3.0f} · {o.titulo[:58]} — R$ {o.preco:.2f}"
           + (f" (-{o.desconto}%)" if o.desconto else "") + (f" · {marca}" if marca else ""))
    com_marca = sum(1 for o in passam if qualidade.marca_boa(o))
    _p(f"\n   De marca conhecida entre os que passam: {com_marca} de {len(passam)}")
    return bool(top)


def _d_api_app() -> bool:
    from .sources.mercadolivre import cliente_padrao
    itens = cliente_padrao().buscar(str(config.fonte_ml.get("site") or "MLB"), q="tênis", limite=5)
    _p(f"   {'✅' if itens else '⚪'} {len(itens)} resultados")
    return bool(itens)


def _f_ia() -> bool:
    """IA (ChatGPT) + conferência na API do ML. Só roda com a IA ligada no painel (é paga)."""
    from .sources import ia_ofertas as ia
    op = ia.opcoes()
    if not config.openai_api_key:
        _p("   ⚪ sem OPENAI_API_KEY no .env (aba Contas do painel)")
        return False
    if not op["ativa"]:
        c = ia.estimativa(op)
        _p(f"   ⚪ IA desligada no painel — não testei (é paga: ≈ US$ {c['por_busca']:.2f} por busca)")
        return False
    if op["gasto_max_mes_usd"] and ia.gasto_do_mes() >= op["gasto_max_mes_usd"]:
        _p(f"   ⚪ gasto do mês já chegou no teto (US$ {op['gasto_max_mes_usd']:.2f})")
        return False
    try:
        sugestoes, uso = ia.pedir_sugestoes(op)
    finally:
        _copiar_diagnostico_ia()
    ia._registrar_busca(uso["custo"], time.time())
    ofertas, descartadas = ia.conferir(sugestoes)
    _p(f"   {'✅' if ofertas else '❌'} {uso['da_lista']} da lista da IA + {uso['das_pesquisas']} links achados "
       f"nas pesquisas → {len(ofertas)} conferidas na API do ML, {descartadas} descartadas · "
       f"{uso['pesquisas']} pesquisas · custo US$ {uso['custo']:.3f}")
    _p(f"        {_resumo(ofertas)}")
    _p("   (resposta da IA em data/teste_fontes/f_ia_resposta.txt)")
    return bool(ofertas)


def _copiar_diagnostico_ia() -> None:
    from .sources import ia_ofertas as ia
    try:
        (PASTA / "f_ia_resposta.txt").write_text(ia.ARQ_ULTIMA_RESPOSTA.read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    except OSError:
        pass


def rodar() -> None:
    log = logging.getLogger("ofertas")
    nivel = log.level
    log.setLevel(logging.WARNING)  # só o resultado na tela
    try:
        _rodar()
    finally:
        log.setLevel(nivel)


def _rodar() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    _linhas.clear()
    _p("Teste das fontes de ofertas — nada é enviado aos grupos")
    _p(time.strftime("%d/%m/%Y %H:%M"))
    res = {"A": _teste("A. Mercado Livre pela API (mais vendidos + catálogo, automático)", _a_mercado_livre),
           "B": _teste("B. Shopee (listas prontas, sem palavra-chave)", _b_shopee),
           "D1": _teste("D1. Busca da API do ML com a chave do app", _d_api_app)}
    res["H"] = _teste("H. Moda no grupo de ofertas gerais: o que o bot mandaria (rankings + filtros + nota)", _h_moda)
    res["G"] = _teste("G. Em alta no ML (mais buscados agora, grátis) + catálogo", _g_em_alta)
    res["F"] = _teste("F. IA (ChatGPT) pesquisando ofertas + conferência na API do ML", _f_ia)
    _p("\n══ Resumo: " + " · ".join(f"{k} {'✅' if v else '❌'}" for k, v in res.items()))
    (PASTA / "resultado.txt").write_text("\n".join(_linhas) + "\n", encoding="utf-8")
    print(f"\nResultado salvo em {PASTA / 'resultado.txt'} — mande esse arquivo (ou um print desta tela).")
