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


def test_le_poucas_paginas_e_abastece_os_grupos(monkeypatch, ciclo):
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
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {u: _pagina(_card("9", "Polo Tommy")) for u in urls})
    a, b = Grupo("a", "A", ofertas_gerais=True), Grupo("b", "B", ofertas_gerais=True)
    ml_geral.atualizar([a, b])
    [oa], [ob] = ml_geral.ofertas_para(a), ml_geral.ofertas_para(b)
    oa.url_afiliado = "https://meli.la/a"
    assert oa is not ob and ob.url_afiliado == ""


def test_pagina_barrada_pausa_e_avisa(monkeypatch, caplog):
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
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {u: _pagina(_card("5", "Tênis New Balance 460")) for u in urls})
    g = Grupo("geral", "Geral", ofertas_gerais=True)
    assert pipeline.executar_ciclo(ciclo, [g], registrar=False) == 1
    assert ciclo.envios[0][1] == "MLB0000000005"


def test_sem_pagina_usa_o_catalogo_pelos_tipos_de_produto(monkeypatch, ciclo):
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {})
    monkeypatch.setattr(pipeline.mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "termos_da_vez", lambda g, c: ["Tênis", "Relógios"])
    buscados = []

    def catalogo(termo, cliente):
        buscados.append(termo)
        if termo == "Tênis":
            return []
        o = Oferta("mercadolivre", "MLB77", "Relógio Casio G-Shock", "https://ml/77", 400, 600, posicao=1)
        return [o]
    monkeypatch.setattr(ml_geral, "catalogo", catalogo)
    g = Grupo("geral", "Geral", ofertas_gerais=True)
    pipeline.executar_ciclo(ciclo, [g], registrar=False)
    assert buscados == ["Tênis", "Relógios"] and ciclo.envios[0][1] == "MLB77"


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
    assert "https://meli.la/1\n⚠️ Preço e disponibilidade podem variar.\n\n" in msg


def test_log_do_catalogo(monkeypatch, ciclo, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {})
    monkeypatch.setattr(pipeline.mercadolivre, "cliente_padrao", lambda: object())
    monkeypatch.setattr(ml_geral, "termos_da_vez", lambda g, c: ["Mochilas"])
    monkeypatch.setattr(ml_geral, "catalogo", lambda termo, cliente: [])
    pipeline.executar_ciclo(ciclo, [Grupo("g", "G", ofertas_gerais=True)], registrar=False)
    assert any("Catálogo do ML 'Mochilas': 0 coletadas" in r.message for r in caplog.records)
