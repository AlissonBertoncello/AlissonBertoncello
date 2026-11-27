"""F1 (ofertas gerais do ML + catálogo de reserva), V3 (mais vendido sem desconto),
M1 (link rastreável por grupo), M5 (aviso de preço) e R2b (página vazia = bloqueio)."""
import logging

import pytest

from ofertas import config as cfg
from ofertas import pipeline
from ofertas.config import config
from ofertas.models import ConfigCupons, Grupo, Oferta
from ofertas.sources import mercadolivre, ml_geral, ml_pagina


def _card(id_, titulo, desconto=40):
    preco = 100 - desconto
    return f"""<div class="poly-card">
  <a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-{int(id_):010d}-x-_JM">{titulo}</a>
  <s class="andes-money-amount--previous"><span class="andes-money-amount__fraction">100</span></s>
  <div class="poly-price__current"><span class="andes-money-amount__fraction">{preco}</span></div>
  <span class="poly-price__discount-polylabel">{desconto}% OFF</span>
</div>"""


def _pagina(*cards):
    return "<html><head><title>Ofertas</title></head><body>" + "".join(cards) + "</body></html>"


class Destino:
    nome = "console"

    def __init__(self):
        self.envios = []

    def enviar(self, o, msg, grupo):
        self.envios.append((grupo.chave, o.id_produto, o.url_afiliado, msg))


@pytest.fixture
def ciclo(monkeypatch):
    for nome in ("_proxima", "_proxima_shopee", "_loja_da_vez"):
        monkeypatch.setattr(pipeline, nome, {})
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True})
    monkeypatch.setattr(config, "fonte_shopee", {"ativa": False})
    monkeypatch.setattr(config, "max_posts_por_ciclo", 1)
    monkeypatch.setattr(config, "desconto_minimo", 10)
    monkeypatch.setattr(config, "preco_minimo", 0)
    monkeypatch.setattr(config, "preco_maximo", 0)
    monkeypatch.setattr(config, "palavras_bloqueadas", [])
    monkeypatch.setattr(config, "cupons", ConfigCupons(horarios=[]))
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)
    etiquetas = []

    def gerar(lista, etiqueta=""):
        etiquetas.append((etiqueta, [o.id_produto for o in lista]))
        for o in lista:
            o.url_afiliado = f"https://meli.la/{etiqueta or 'padrao'}/{o.id_produto}"
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    d = Destino()
    d.etiquetas = etiquetas
    return d


# ── F1a: página geral de ofertas ─────────────────────────────────────

T = 1_800_000_000.0


def _ligar_pagina(monkeypatch):
    """A página de ofertas do ML é opcional e vem desligada (o ML barra o acesso)."""
    fonte = dict(config.fonte_ml or {})
    fonte["ativa"] = True
    fonte["ofertas_gerais"] = {**(fonte.get("ofertas_gerais") or {}), "pagina_ofertas": True}
    monkeypatch.setattr(config, "fonte_ml", fonte)


def test_pagina_de_ofertas_ligada_por_padrao_geral_e_moda(monkeypatch):
    """Desde 26/11 a API não dá o preço: a página de ofertas (geral + moda) é a fonte do ML."""
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True})
    lidas = []
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: lidas.extend(urls) or
                        {u: _pagina(_card(str(i + 1), "Tênis Nike Court Vision")) for i, u in enumerate(urls)})
    g = Grupo("g", "G", ofertas_gerais=True)
    ml_geral.atualizar([g], agora=T)
    assert lidas == ["https://www.mercadolivre.com.br/ofertas", "https://www.mercadolivre.com.br/ofertas?category=MLB1430"]
    assert len(ml_geral.ofertas_para(g)) == 2


def test_pagina_de_ofertas_pode_ser_desligada(monkeypatch):
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True, "ofertas_gerais": {"pagina_ofertas": False}})
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: pytest.fail("abriu o Chrome"))
    ml_geral.atualizar([Grupo("g", "G", ofertas_gerais=True)], agora=T)


def test_le_poucas_paginas_e_abastece_os_grupos(monkeypatch, ciclo):
    _ligar_pagina(monkeypatch)
    monkeypatch.setattr(ml_geral, "FONTES_PADRAO", [""])
    lidas = []

    def chrome(urls):
        lidas.extend(urls)
        return {u: _pagina(_card(f"{len(lidas)}1", "Tênis Nike Revolution"), _card(f"{len(lidas)}2", "Trena Stanley 5m"))
                for u in urls}
    monkeypatch.setattr(ml_geral, "_chrome_ler", chrome)
    geral = Grupo("geral", "Geral", ofertas_gerais=True)
    beleza = Grupo("beleza", "Beleza", ofertas_gerais=True, departamentos={"MLB1246": "Beleza"})
    ml_geral.atualizar([geral, beleza], agora=T)
    # 2 páginas por ciclo no total, uma de cada fonte
    assert lidas == ["https://www.mercadolivre.com.br/ofertas", "https://www.mercadolivre.com.br/ofertas?category=MLB1246"]
    assert len(ml_geral.ofertas_para(geral)) == 2 and len(ml_geral.ofertas_para(beleza)) == 2
    # dentro de atualizar_minutos não lê de novo
    ml_geral.atualizar([geral, beleza], agora=T + 60)
    assert len(lidas) == 2
    # depois lê a página seguinte
    ml_geral.atualizar([geral], agora=T + 31 * 60)
    assert lidas[-2:] == ["https://www.mercadolivre.com.br/ofertas?page=2", "https://www.mercadolivre.com.br/ofertas?page=3"]


def test_cada_grupo_recebe_copia_com_link_proprio(monkeypatch):
    _ligar_pagina(monkeypatch)
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {u: _pagina(_card("9", "Polo Tommy")) for u in urls})
    a, b = Grupo("a", "A", ofertas_gerais=True), Grupo("b", "B", ofertas_gerais=True)
    ml_geral.atualizar([a, b])
    [oa], [ob] = ml_geral.ofertas_para(a), ml_geral.ofertas_para(b)
    oa.url_afiliado = "https://meli.la/a"
    assert oa is not ob and ob.url_afiliado == ""


def test_pagina_barrada_pausa_e_avisa(monkeypatch, caplog):
    _ligar_pagina(monkeypatch)
    lidas = []
    vazia = "<html><head></head><body></body></html>"  # ~200 bytes, sem título (R2b)
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: lidas.extend(urls) or {u: vazia for u in urls})
    g = Grupo("g", "G", ofertas_gerais=True)
    ml_geral.atualizar([g])
    assert ml_geral.pausada() and any("barrou a página de ofertas" in r.message for r in caplog.records)
    ml_geral.atualizar([g])
    assert len(lidas) == 2  # pausada: não abre o Chrome de novo


def test_r2b_pagina_vazia_e_bloqueio():
    assert ml_pagina.e_bloqueio("<html><head></head><body></body></html>")
    assert ml_pagina.e_bloqueio("<html><head><title>Segurança — Mercado Livre</title></head></html>")
    # tela "Olá! Para continuar, acesse sua conta" (tráfego suspeito), que veio no teste E
    verificacao = ("<html><head><title>Mercado Libre</title></head><body>Olá! Para continuar, acesse sua conta"
                   "<script>location='/gz/account-verification?go=x&reason=suspicious-traffic'</script>"
                   + "x" * 5000 + "</body></html>")
    assert ml_pagina.e_bloqueio(verificacao)
    assert not ml_pagina.e_bloqueio(_pagina(_card("1", "x")))
    assert not ml_pagina.e_bloqueio(None)


def test_com_ofertas_gerais_nao_le_a_pagina_de_cada_categoria(monkeypatch):
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True, "modo": "auto"})
    monkeypatch.setattr(config, "usa_ofertas_gerais", True)
    monkeypatch.setattr(mercadolivre, "_buscar_api", lambda *a, **k: {})
    chamou = []
    monkeypatch.setattr(mercadolivre, "_via_pagina_ofertas", lambda cats: chamou.append(cats) or [])
    mercadolivre.buscar_ofertas(object(), {"MLB1": "x"})
    assert chamou == []


# ── pipeline: ofertas gerais -> categorias -> catálogo ───────────────

def test_grupo_geral_envia_da_pagina_de_ofertas(monkeypatch, ciclo):
    _ligar_pagina(monkeypatch)
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {u: _pagina(_card("5", "Tênis New Balance 460")) for u in urls})
    g = Grupo("geral", "Geral", ofertas_gerais=True)
    assert pipeline.executar_ciclo(ciclo, [g], registrar=False) == 1
    assert ciclo.envios[0][1] == "MLB0000000005"


def test_sem_pagina_usa_mais_vendidos_e_catalogo_automaticos(monkeypatch, ciclo):
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {})
    monkeypatch.setattr(pipeline.mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: [("MLB1", "Tênis"), ("MLB2", "Relógios")])
    buscados = []
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: buscados.append(("ranking", cid)) or [])

    def catalogo(termo, cliente):
        buscados.append(("catálogo", termo))
        if termo == "Tênis":
            return []
        return [Oferta("mercadolivre", "MLB77", "Relógio Casio G-Shock", "https://ml/77", 400, 600, posicao=1)]
    monkeypatch.setattr(ml_geral, "catalogo", catalogo)
    g = Grupo("geral", "Geral", ofertas_gerais=True)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert buscados == [("ranking", "MLB1"), ("catálogo", "Tênis"), ("ranking", "MLB2"), ("catálogo", "Relógios")]
    assert ciclo.envios[0][1] == "MLB77"


def test_grupo_geral_prefere_os_automaticos_as_categorias_antigas(monkeypatch, ciclo):
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {})
    monkeypatch.setattr(pipeline.mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: [("MLB9", "Mochilas")])
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: [
        Oferta("mercadolivre", "MLB55", "Mochila Nike Academy", "https://ml/55", 150, 250, posicao=1)])
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [Oferta("mercadolivre", "MLB66", "Shampoo Automotivo", "https://ml/66", 30, 50)])
    g = Grupo("geral", "Geral", {"MLB188063": "Limpeza Automotiva"}, ofertas_gerais=True)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert ciclo.envios[0][1] == "MLB55"


def test_pagina_aberta_sem_ofertas_pausa_e_guarda_copia(monkeypatch, caplog):
    _ligar_pagina(monkeypatch)
    html = "<html><head><title>Informe seu CEP</title></head><body>" + "x" * 5000 + "</body></html>"
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {u: html for u in urls})
    monkeypatch.setattr(ml_geral, "DATA_DIR", ml_geral.ARQ_TERMOS.parent)
    ml_geral.atualizar([Grupo("g", "G", ofertas_gerais=True)])
    assert ml_geral.pausada()
    assert any("sem ofertas reconhecíveis (título: 'Informe seu CEP'" in r.message for r in caplog.records)
    assert (ml_geral.ARQ_TERMOS.parent / "ml_geral_debug.html").read_text(encoding="utf-8") == html


def test_termos_vem_das_subcategorias_do_ml(monkeypatch):
    class Cliente:
        def categoria(self, cid):
            arvore = {"MLB1430": [{"id": "A", "name": "Calçados"}, {"id": "B", "name": "Bolsas"}],
                      "A": [{"id": "A1", "name": "Tênis"}, {"id": "A2", "name": "Outros"}], "B": []}
            return {"children_categories": arvore[cid]}

        def categorias_raiz(self, site):
            return [{"id": "MLB1430", "name": "Calçados, Roupas e Bolsas"}, {"id": "MLB1459", "name": "Imóveis"}]
    c = Cliente()
    assert ml_geral.termos_do_departamento("MLB1430", c) == ["Tênis", "Bolsas"]
    g = Grupo("g", "G", ofertas_gerais=True)
    assert ml_geral.termos_da_vez(g, c, qtd=2) == ["Tênis", "Bolsas"]  # sem Imóveis, sem "Outros"
    assert ml_geral.ARQ_TERMOS.exists()  # guardado para a próxima vez


def test_config_aceita_grupo_so_com_ofertas_gerais():
    [g] = cfg.ler_grupos({"x": {"ofertas_gerais": True, "departamentos": {"mlb1246": "Beleza"},
                                "sem_desconto": True, "etiqueta_ml": "tag_x"}})
    assert g.ofertas_gerais and g.departamentos == {"MLB1246": "Beleza"}
    assert g.sem_desconto and g.etiqueta_ml == "tag_x"


# ── V3: mais vendido sem desconto ────────────────────────────────────

def test_mais_vendido_sem_desconto(monkeypatch):
    monkeypatch.setattr(config, "desconto_minimo", 10)
    monkeypatch.setattr(config, "preco_minimo", 0)
    monkeypatch.setattr(config, "preco_maximo", 0)
    monkeypatch.setattr(config, "palavras_bloqueadas", [])
    top = Oferta("mercadolivre", "1", "Whey Growth", "https://ml/1", 99.0, posicao=2)
    longe = Oferta("mercadolivre", "2", "Whey Max", "https://ml/2", 99.0, posicao=9)
    pouco = Oferta("mercadolivre", "3", "Creatina", "https://ml/3", 97.0, 100.0, posicao=1)
    assert pipeline.motivo_descarte(top, "g", [], sem_desconto=True) is None
    assert pipeline.motivo_descarte(top, "g", [], sem_desconto=False) == "desconto < 10%"
    assert pipeline.motivo_descarte(longe, "g", [], sem_desconto=True) == "desconto < 10%"
    assert pipeline.motivo_descarte(pouco, "g", [], sem_desconto=True) == "desconto < 10%"  # 3% não é "sem desconto"


def test_mensagem_sem_desconto_mostra_so_o_preco():
    from ofertas.formatter import montar_mensagem
    msg = montar_mensagem(Oferta("mercadolivre", "1", "Whey Growth", "https://ml/1", 99.0))
    assert "Por *R$ 99*" in msg and "De ~" not in msg


# ── M1: link rastreável por grupo ────────────────────────────────────

def test_etiqueta_do_ml_por_grupo(monkeypatch, ciclo):
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [Oferta("mercadolivre", next(iter(cats)), "Item " + next(iter(cats)),
                                                                  "https://ml/x", 50, 100)])
    a = Grupo("a", "A", {"C1": "x"}, etiqueta_ml="tag_a")
    b = Grupo("b", "B", {"C2": "y"})
    pipeline.executar_ciclo(ciclo, [a, b], registrar=False)
    assert sorted(ciclo.etiquetas) == [("", ["C2"]), ("tag_a", ["C1"])]
    assert {e[0]: e[2] for e in ciclo.envios} == {"a": "https://meli.la/tag_a/C1", "b": "https://meli.la/padrao/C2"}


def test_link_da_shopee_com_o_grupo_como_sub_id(monkeypatch, ciclo):
    monkeypatch.setattr(config, "fonte_shopee", {"ativa": True})
    monkeypatch.setattr(config, "shopee_app_id", "id")
    monkeypatch.setattr(config, "shopee_app_secret", "s")
    pedidos = []
    monkeypatch.setattr(pipeline.shopee, "link_afiliado",
                        lambda url, sub_id="": pedidos.append((url, sub_id)) or f"https://s.shopee.com.br/{sub_id}")
    o = Oferta("shopee", "1", "Fone Bluetooth", "https://shopee.com.br/produto-i.1.2", 50, 100,
               url_afiliado="https://s.shopee.com.br/padrao")
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: [o])
    g = Grupo("confraria", "C", shopee=["fone"], peso_ml=0, peso_shopee=1)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert pedidos == [("https://shopee.com.br/produto-i.1.2", "confraria")]
    assert ciclo.envios[0][2] == "https://s.shopee.com.br/confraria"


def test_se_a_shopee_nao_gera_o_link_por_grupo_fica_o_normal(monkeypatch, ciclo):
    monkeypatch.setattr(config, "fonte_shopee", {"ativa": True})
    monkeypatch.setattr(config, "shopee_app_id", "id")
    monkeypatch.setattr(config, "shopee_app_secret", "s")
    o = Oferta("shopee", "1", "Fone", "https://shopee.com.br/p", 50, 100, url_afiliado="https://s.shopee.com.br/padrao")
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: [o])
    g = Grupo("g", "G", shopee=["fone"], peso_ml=0, peso_shopee=1)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)  # conftest: link_afiliado sempre falha
    assert ciclo.envios[0][2] == "https://s.shopee.com.br/padrao"


# ── M5: aviso de preço ───────────────────────────────────────────────

def test_aviso_de_preco_vem_logo_abaixo_do_link():
    from ofertas.formatter import montar_mensagem
    g = Grupo("g", "G", convite="https://chat.whatsapp.com/X")
    msg = montar_mensagem(Oferta("mercadolivre", "1", "Fone", "https://ml/1", 50, 100, url_afiliado="https://meli.la/1"), g)
    assert "https://meli.la/1\n\n⚠️ Preço e disponibilidade podem variar.\n\n" in msg


def test_log_do_catalogo(monkeypatch, ciclo, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {})
    monkeypatch.setattr(pipeline.mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: [("MLB9", "Mochilas")])
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: [])
    monkeypatch.setattr(ml_geral, "catalogo", lambda termo, cliente: [])
    pipeline.executar_ciclo(ciclo, [Grupo("g", "G", ofertas_gerais=True)], registrar=False)
    assert any("Mais vendidos 'Mochilas': 0 coletadas" in r.message for r in caplog.records)
    assert any("Catálogo do ML 'Mochilas': 0 coletadas" in r.message for r in caplog.records)


# ── B: lista de mais vendidos da Shopee ──────────────────────────────

def _shopee_ligada(monkeypatch):
    monkeypatch.setattr(config, "fonte_shopee", {"ativa": True})
    monkeypatch.setattr(config, "shopee_app_id", "id")
    monkeypatch.setattr(config, "shopee_app_secret", "s")


def test_grupo_geral_usa_a_lista_de_mais_vendidos_da_shopee(monkeypatch, ciclo):
    _shopee_ligada(monkeypatch)
    paginas = []
    monkeypatch.setattr(pipeline.shopee, "mais_vendidos", lambda pagina: paginas.append(pagina) or [
        Oferta("shopee", f"S{pagina}", f"Fone Bluetooth {pagina}", "https://s/p", 50, 100, url_afiliado="https://s.shopee.com.br/x")])
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: pytest.fail("não devia buscar palavra"))
    g = Grupo("geral", "Geral", shopee=["fone"], ofertas_gerais=True, peso_ml=0, peso_shopee=1)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert paginas == [1, 2] and [e[1] for e in ciclo.envios] == ["S1", "S2"]


def test_lista_recusada_pela_shopee_volta_para_as_palavras(monkeypatch, ciclo, caplog):
    _shopee_ligada(monkeypatch)
    from ofertas.sources.shopee import ErroShopee
    tentativas = []

    def recusa(pagina):
        tentativas.append(pagina)
        raise ErroShopee("Shopee API: Unknown argument listType")
    monkeypatch.setattr(pipeline.shopee, "mais_vendidos", recusa)
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: [
        Oferta("shopee", "K1", "Fone JBL", "https://s/p", 50, 100, url_afiliado="https://s.shopee.com.br/k")])
    g = Grupo("geral", "Geral", shopee=["fone"], ofertas_gerais=True, peso_ml=0, peso_shopee=1)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert tentativas == [1]  # não insiste depois de recusada
    assert [e[1] for e in ciclo.envios] == ["K1", "K1"] or ciclo.envios[0][1] == "K1"
    assert sum("não aceitou a lista de mais vendidos" in r.message for r in caplog.records) == 1


def test_grupo_de_nicho_nao_usa_a_lista_geral_da_shopee(monkeypatch, ciclo):
    _shopee_ligada(monkeypatch)
    monkeypatch.setattr(pipeline.shopee, "mais_vendidos", lambda pagina: pytest.fail("grupo de nicho"))
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: [
        Oferta("shopee", "B1", "Batom", "https://s/p", 20, 40, url_afiliado="https://s.shopee.com.br/b")])
    g = Grupo("gabi", "Gabi", shopee=["batom"], ofertas_gerais=True, departamentos={"MLB1246": "Beleza"},
              peso_ml=0, peso_shopee=1)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert ciclo.envios[0][1] == "B1"


def test_consulta_da_lista_de_mais_vendidos(monkeypatch):
    from ofertas.sources import shopee
    consultas = []
    monkeypatch.setattr(shopee, "chamar", lambda q: consultas.append(q) or {"productOfferV2": {"nodes": [
        {"itemId": 1, "productName": "Fone", "offerLink": "https://s/1", "priceMin": "50", "priceDiscountRate": 20}]}})
    [o] = shopee.mais_vendidos(pagina=2, limite=10)
    assert "listType:2,sortType:2,page:2,limit:10" in consultas[0] and o.posicao == 11


def test_testar_fontes_grava_o_resultado_mesmo_com_erros(monkeypatch, tmp_path):
    from ofertas import teste_fontes
    monkeypatch.setattr(teste_fontes, "PASTA", tmp_path)
    monkeypatch.setattr(teste_fontes, "_a_mercado_livre", lambda: True)
    monkeypatch.setattr(teste_fontes, "_b_shopee", lambda: (_ for _ in ()).throw(RuntimeError("Shopee fora")))
    monkeypatch.setattr(teste_fontes, "_d_api_app", lambda: False)
    monkeypatch.setattr(teste_fontes, "_f_ia", lambda: True)
    monkeypatch.setattr(teste_fontes, "_g_em_alta", lambda: True)
    monkeypatch.setattr(teste_fontes, "_h_moda", lambda: False)
    teste_fontes.rodar()
    texto = (tmp_path / "resultado.txt").read_text(encoding="utf-8")
    assert "❌ erro: Shopee fora" in texto
    assert "Resumo: A ✅ · B ❌ · D1 ❌ · H ❌ · G ✅ · F ✅" in texto
