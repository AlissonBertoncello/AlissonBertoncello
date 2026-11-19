"""Testa, no notebook, de onde o bot consegue trazer ofertas (não envia nada aos grupos).

    uv run python -m ofertas testar-fontes        (ou TESTAR_FONTES.bat)

A. Mercado Livre pela API: mais vendidos e catálogo das subcategorias, automático
B. Shopee: lista de mais vendidos sem palavra-chave (e uma busca por palavra, para comparar)
C. Página de ofertas do ML lida de dentro do login de afiliado (janela do Linkbuilder)
D. Busca completa da API do ML (com a chave do app e de dentro do login)
E. Página geral de ofertas no Chrome separado (o jeito atual das ofertas gerais)

O resultado fica em data/teste_fontes/resultado.txt (sem senhas nem dados da conta) e a
página do teste E em data/teste_fontes/e_pagina_geral.html (navegador sem login).
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


def _c_e_d_logado() -> tuple[bool, bool]:
    """C (página de ofertas) e D (API) lidos de dentro da janela logada do Linkbuilder."""
    from . import afiliado_ml
    from .sources import ml_pagina
    ok_c = ok_d = False
    with afiliado_ml.pagina_chrome() as page:
        afiliado_ml._abrir_linkbuilder(page)
        _p("\n── C. Página de ofertas lida de dentro do login de afiliado")
        r = page.evaluate("""async (url) => {
            try { const resp = await fetch(url, {credentials: 'include'});
                  return {http: resp.status, html: await resp.text()}; }
            catch (e) { return {erro: String(e)}; } }""", ml_pagina.URL_OFERTAS)
        if r.get("erro"):
            _p(f"   ❌ {r['erro'][:200]}")
        else:
            html = r.get("html") or ""
            achadas = ml_pagina.parse_pagina(html)
            ok_c = bool(achadas)
            situacao = "barrada" if ml_pagina.e_bloqueio(html) else ("ok" if achadas else "sem ofertas reconhecíveis")
            _p(f"   {'✅' if achadas else '❌'} HTTP {r.get('http')}, título {ml_pagina._titulo(html)!r}, "
               f"{len(html)} bytes — {situacao}: {_resumo(achadas)}")
        _p("\n── D2. Busca da API do ML de dentro do login")
        r = page.evaluate("""async () => {
            try { const resp = await fetch('https://api.mercadolibre.com/sites/MLB/search?q=tenis&limit=5');
                  const j = await resp.json().catch(() => ({}));
                  return {http: resp.status, n: (j.results || []).length}; }
            catch (e) { return {erro: String(e)}; } }""")
        if r.get("erro"):
            _p(f"   ❌ {r['erro'][:200]}")
        else:
            ok_d = bool(r.get("n"))
            _p(f"   {'✅' if ok_d else '❌'} HTTP {r.get('http')}, {r.get('n')} resultados")
    return ok_c, ok_d


def _d_api_app() -> bool:
    from .sources.mercadolivre import cliente_padrao
    itens = cliente_padrao().buscar(str(config.fonte_ml.get("site") or "MLB"), q="tênis", limite=5)
    _p(f"   {'✅' if itens else '⚪'} {len(itens)} resultados")
    return bool(itens)


def _e_pagina_geral() -> bool:
    from .sources import ml_geral, ml_pagina
    htmls = ml_geral._chrome_ler([ml_pagina.URL_OFERTAS])
    html = htmls.get(ml_pagina.URL_OFERTAS)
    if html is None:
        _p("   ❌ a página não abriu")
        return False
    (PASTA / "e_pagina_geral.html").write_text(html, encoding="utf-8")
    achadas = ml_pagina.parse_pagina(html)
    situacao = "barrada" if ml_pagina.e_bloqueio(html) else ("ok" if achadas else "sem ofertas reconhecíveis")
    _p(f"   {'✅' if achadas else '❌'} título {ml_pagina._titulo(html)!r}, {len(html)} bytes — "
       f"{situacao}: {_resumo(achadas)}")
    _p("   (cópia da página em data/teste_fontes/e_pagina_geral.html)")
    return bool(achadas)


def rodar() -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    _linhas.clear()
    logging.getLogger("ofertas").setLevel(logging.WARNING)  # só o resultado na tela
    _p("Teste das fontes de ofertas — nada é enviado aos grupos")
    _p(time.strftime("%d/%m/%Y %H:%M"))
    res = {"A": _teste("A. Mercado Livre pela API (mais vendidos + catálogo, automático)", _a_mercado_livre),
           "B": _teste("B. Shopee (listas prontas, sem palavra-chave)", _b_shopee),
           "D1": _teste("D1. Busca da API do ML com a chave do app", _d_api_app)}
    try:
        res["C"], res["D2"] = _c_e_d_logado()
    except Exception as e:
        _p(f"\n── C/D2: o Linkbuilder (login de afiliado) não abriu no Chrome: {str(e).splitlines()[0][:200]}")
        res["C"] = res["D2"] = False
    res["E"] = _teste("E. Página geral de ofertas no Chrome separado (jeito atual)", _e_pagina_geral)
    _p("\n══ Resumo: " + " · ".join(f"{k} {'✅' if v else '❌'}" for k, v in res.items()))
    (PASTA / "resultado.txt").write_text("\n".join(_linhas) + "\n", encoding="utf-8")
    print(f"\nResultado salvo em {PASTA / 'resultado.txt'} — mande esse arquivo (ou um print desta tela).")
