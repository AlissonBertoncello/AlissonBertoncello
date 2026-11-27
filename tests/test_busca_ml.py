from ofertas import busca_ml
from ofertas.sources import ml_pagina
from ofertas.sources.mercadolivre import ErroAPI

CARD = """<div class="poly-card"><a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-1234567890-tenis-_JM">Tênis Nike</a>
<div class="poly-price__current"><span class="andes-money-amount__fraction">199</span></div></div>"""


class Cliente:
    def token(self):
        return "t"

    def get(self, caminho, params=None):
        if caminho.startswith("/highlights"):
            return {"content": [{"id": "MLB1", "type": "ITEM"}, {"id": "MLB2", "type": "PRODUCT"},
                                {"id": "MLBU3", "type": "USER_PRODUCT"}]}
        if caminho == "/items":
            return [{"code": 200, "body": {"title": "Fone JBL", "price": 99.0, "original_price": 199.0,
                                           "permalink": "https://ml/1"}}]
        if caminho == "/products/MLB2":
            return {"name": "Relógio Casio", "buy_box_winner": None}
        if caminho == "/products/MLB2/items":
            raise ErroAPI("GET /products/MLB2/items respondeu HTTP 403: forbidden")
        if caminho.startswith("/user-products"):
            raise ErroAPI("HTTP 404")
        if caminho == "/products/search":
            return {"results": [{"id": "MLB9", "name": "Tênis Nike Air"}]}
        if caminho == "/products/MLB9/items":
            return {"results": [{"price": 299.0, "original_price": 499.0}]}
        raise ErroAPI("HTTP 404")


def test_busca_crua_mostra_cada_caminho(monkeypatch, tmp_path):
    monkeypatch.setattr(busca_ml, "PASTA", tmp_path)
    monkeypatch.setattr(busca_ml, "CATEGORIAS", {"MLB1430": "Moda"})
    monkeypatch.setattr(busca_ml, "PALAVRAS", ["tênis nike"])
    monkeypatch.setattr(busca_ml.ClienteML, "do_config", classmethod(lambda cls: Cliente()))
    monkeypatch.setattr(ml_pagina, "_html_navegador",
                        lambda urls: {u: f"<html><head><title>Ofertas</title></head><body>{CARD}</body></html>" for u in urls})
    busca_ml.rodar()
    texto = (tmp_path / "resultado.txt").read_text(encoding="utf-8")
    assert "página de ofertas: 3" in texto  # 3 páginas, 1 produto cada
    assert "Fone JBL — R$ 99.00 (de R$ 199.00)" in texto
    assert "Relógio Casio — SEM PREÇO" in texto and "HTTP 403" in texto  # mostra onde o preço some
    assert "USER_PRODUCT MLBU3: ❌ HTTP 404" in texto
    assert "Tênis Nike Air — R$ 299.00" in texto
    assert (tmp_path / "api_ranking_MLB1430.json").exists() and (tmp_path / "pagina_1.html").exists()


# ── P: página de ofertas como fonte do ML (27/11) ───────────────────

def _card(href, titulo="Tênis Nike Court Vision", preco="249", antes="599"):
    return f"""<div class="poly-card"><a class="poly-component__title" href="{href}">{titulo}</a>
<s class="andes-money-amount--previous"><span class="andes-money-amount__fraction">{antes}</span></s>
<div class="poly-price__current"><span class="andes-money-amount__fraction">{preco}</span></div></div>"""


def test_card_patrocinado_usa_o_link_real_do_produto():
    click = ("https://click1.mercadolivre.com.br/mclics/clicks/external/MLB/count?a=xyz&url="
             "https%3A%2F%2Fproduto.mercadolivre.com.br%2FMLB-6897809208-tenis-torx-_JM%23position%3D7&lm=1")
    sem_url = "https://click1.mercadolivre.com.br/mclics/clicks/external/MLB/count?a=xyz"
    html = "<html><body>" + _card(click) + _card(sem_url, "Sem link") + "</body></html>"
    [o] = ml_pagina.parse_pagina(html)
    assert o.url_produto == "https://produto.mercadolivre.com.br/MLB-6897809208-tenis-torx-_JM"
    assert o.id_produto == "MLB6897809208" and o.desconto == 58


def test_ids_de_catalogo_e_de_produto_do_vendedor():
    html = "<html><body>" + _card("https://www.mercadolivre.com.br/celular-samsung/p/MLB78270054#x") \
        + _card("https://www.mercadolivre.com.br/kit-3-t-shirts/up/MLBU4286899840#s", "Kit 3 T-shirts") + "</body></html>"
    a, b = ml_pagina.parse_pagina(html)
    assert (a.id_produto, a.url_produto) == ("MLB78270054", "https://www.mercadolivre.com.br/celular-samsung/p/MLB78270054")
    assert b.id_produto == "MLBU4286899840"


def test_api_sem_preco_fica_pulada_e_o_clube_segue_pela_pagina(monkeypatch, caplog):
    from ofertas import pipeline
    from ofertas.config import config
    from ofertas.models import Grupo, Oferta
    from ofertas.sources import mercadolivre, ml_geral
    monkeypatch.setattr(config, "fonte_ml", {"ativa": True})
    monkeypatch.setattr(config, "desconto_minimo", 10)
    monkeypatch.setattr(config, "palavras_bloqueadas", [])
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: object())
    chamadas = []
    monkeypatch.setattr(ml_geral, "da_vez", lambda g, c: chamadas.append(1) or [("MLB1", "Tênis")])
    monkeypatch.setattr(ml_geral, "mais_vendidos", lambda cid, c: [])
    monkeypatch.setattr(ml_geral, "catalogo", lambda termo, c, limite=10: [])
    monkeypatch.setattr(ml_geral, "em_alta_da_vez", lambda g, c: [])
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [])
    g = Grupo("clube", "Clube", {"MLB2": "Calças"}, ofertas_gerais=True)
    for _ in range(3):  # 3 buscas seguidas sem nada -> pausa
        assert pipeline._candidatas_ml(g, 1) == []
    assert pipeline.api_ml_pausada() and any("pulada por 6 h" in r.message for r in caplog.records)
    ml_geral.guardar("", [Oferta("mercadolivre", "MLB9", "Tênis Nike Court Vision", "https://ml/9", 249.99, 599.99)])
    antes = len(chamadas)
    assert [o.id_produto for o in pipeline._candidatas_ml(g, 1)] == ["MLB9"]
    ml_geral._estoque.clear()
    assert pipeline._candidatas_ml(g, 1) == [] and len(chamadas) == antes  # API pulada: nem tenta


def test_marcas_novas_da_pagina():
    from ofertas import qualidade
    from ofertas.models import Oferta
    for titulo in ("Kit 10 Cuecas Boxer Lupo Algodão", "Camiseta Polo Core Masculino Insider",
                   "Amazon Echo Dot 5ª Geração"):
        assert qualidade.marca_boa(Oferta("mercadolivre", "x", titulo, "u", 100, 200)), titulo


# ── D: diversidade de categoria e marca (27/11) ─────────────────────

def test_categoria_pelo_titulo():
    from ofertas import qualidade
    casos = {"Tênis Nike Court Vision": "calçados", "Kit 10 Cuecas Boxer Lupo": "roupas",
             "Relógio Tommy Hilfiger David": "acessórios", "Boné Nike Club Swoosh": "acessórios",
             "Fritadeira Air Fryer 5,5l Widemax": "casa e cozinha", "Caixa de Som Boombox AIWA": "eletrônicos",
             "Lavadora de Alta Pressão WAP": "ferramentas", "Máscara de Reconstrução Profunda para Cabelos": "beleza e perfume",
             "Perfume Árabe Masculino": "beleza e perfume", "Whey Protein Growth": "fitness"}
    for titulo, cat in casos.items():
        assert qualidade.categoria(titulo) == cat, titulo


def test_nao_repete_categoria_nem_marca_em_seguida(monkeypatch):
    from ofertas import db, pipeline
    from ofertas.config import config
    from ofertas.models import Grupo, Oferta
    monkeypatch.setattr(config, "palavras_bloqueadas", [])

    def o(i, titulo, preco, antes):
        return Oferta("mercadolivre", f"MLB{i}", titulo, f"https://ml/{i}", preco, antes)
    estoque = [o(1, "Tênis Nike Court Vision Masculino", 250, 600), o(2, "Tênis Nike Court Vision Feminino", 250, 600),
               o(3, "Tênis Kappa Park Unissex", 70, 170), o(4, "Fritadeira Air Fryer Mondial 12L", 399, 880),
               o(5, "Camiseta Polo Insider Core", 115, 275)]
    g = Grupo("clube", "Clube", ofertas_gerais=True, desconto_minimo=15, preco_minimo=25)
    enviados = []
    for _ in range(4):
        restantes = [x for x in estoque if x.id_produto not in enviados]
        [escolhida] = pipeline.escolher_do_grupo(g, restantes, 1)
        db.registrar(escolhida, g.chave)
        enviados.append(escolhida.id_produto)
    # o 1º é o de nota mais alta (Kappa, -59%); depois nunca a mesma categoria em seguida
    assert enviados[0] == "MLB3"
    from ofertas import qualidade
    cats = [qualidade.categoria(next(x.titulo for x in estoque if x.id_produto == i)) for i in enviados]
    assert all(a != b for a, b in zip(cats, cats[1:])), cats
    assert not {"MLB1", "MLB2"} <= set(enviados[:3])  # os dois Nike não saem um logo depois do outro


def test_grupo_comum_nao_muda():
    from ofertas import pipeline
    from ofertas.models import Grupo, Oferta
    a = Oferta("mercadolivre", "A", "Tênis X", "u", 50, 100)
    b = Oferta("mercadolivre", "B", "Tênis Y", "u", 40, 100)
    assert [x.id_produto for x in pipeline.escolher_do_grupo(Grupo("g", "G"), [a, b], 2)] == ["B", "A"]
