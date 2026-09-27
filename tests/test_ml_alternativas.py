from ofertas.sources import mercadolivre, ml_pagina
from ofertas.sources.mercadolivre import ErroAPI, produto_para_oferta

ITEM = {"id": "MLB1", "title": "Fone", "permalink": "https://ml/MLB-1-fone",
        "price": 50, "original_price": 100}
PRODUTO = {"id": "MLB900", "name": "Air Fryer X", "permalink": "https://www.mercadolivre.com.br/air/p/MLB900",
           "pictures": [{"url": "https://img/1.jpg"}],
           "buy_box_winner": {"price": 300, "original_price": 500, "shipping": {"free_shipping": True}}}


class ClienteFalso:
    def __init__(self, busca_403=True):
        self.busca_403 = busca_403
        self.busca_bloqueada = False
        self.rodizio_sub = {}
        self.filhas = {}
        self.chamadas = []

    def subcategorias(self, cat):
        return self.filhas.get(cat, [])

    def buscar(self, site, **kw):
        self.chamadas.append("buscar")
        if self.busca_403:
            raise ErroAPI("GET /sites/MLB/search respondeu HTTP 403: forbidden")
        return [ITEM]

    def destaques(self, site, cat):
        self.chamadas.append("destaques:" + cat)
        return [{"id": "MLB1", "type": "ITEM"}, {"id": "MLB900", "type": "PRODUCT"}]

    def itens(self, ids):
        return [ITEM]

    def produto(self, pid):
        return PRODUTO

    def itens_do_produto(self, pid):
        return []

    def buscar_produtos(self, site, q, limite):
        self.chamadas.append("catalogo")
        return [{"id": "MLB900"}]


def _config(monkeypatch, **fonte):
    monkeypatch.setattr(mercadolivre.config, "fonte_ml",
                        {"ativa": True, "modo": "api", "categorias": {"MLB1648": "Info"}, **fonte})
    monkeypatch.setattr(mercadolivre.time, "sleep", lambda s: None)


def test_produto_para_oferta():
    o = produto_para_oferta(PRODUTO)
    assert (o.titulo, o.preco, o.preco_original, o.desconto) == ("Air Fryer X", 300.0, 500.0, 40)
    assert o.url_produto.endswith("/p/MLB900") and o.imagem == "https://img/1.jpg"
    assert "Frete grátis" in o.extra


def test_produto_sem_preco_ignorado():
    assert produto_para_oferta({"id": "MLB9", "name": "x"}) is None


def test_403_usa_mais_vendidos_e_catalogo(monkeypatch):
    _config(monkeypatch, buscas=["air fryer"])
    c = ClienteFalso()
    ofertas = mercadolivre.buscar_ofertas(c)
    assert sorted(o.id_produto for o in ofertas) == ["MLB1", "MLB900"]
    assert c.chamadas.count("buscar") == 1  # depois do 403 não tenta mais a busca
    assert "catalogo" in c.chamadas and "destaques:MLB1648" in c.chamadas


def test_busca_liberada_usa_busca(monkeypatch):
    _config(monkeypatch)
    c = ClienteFalso(busca_403=False)
    assert [o.id_produto for o in mercadolivre.buscar_ofertas(c)] == ["MLB1"]
    assert not any(ch.startswith("destaques") for ch in c.chamadas)


def test_auto_cai_para_pagina(monkeypatch):
    _config(monkeypatch, modo="auto")
    monkeypatch.setattr(mercadolivre, "_pagina_da_vez", {})

    class SemNada(ClienteFalso):
        def destaques(self, site, cat):
            raise ErroAPI("HTTP 403")
    monkeypatch.setattr(ml_pagina, "buscar_ofertas",
                        lambda cats, paginas, inicio: [mercadolivre.item_para_oferta(ITEM)])
    assert [o.id_produto for o in mercadolivre.buscar_ofertas(SemNada())] == ["MLB1"]


def test_auto_soma_mais_vendidos_e_pagina_de_ofertas(monkeypatch):
    _config(monkeypatch, modo="auto")
    monkeypatch.setattr(mercadolivre, "_pagina_da_vez", {})
    da_pagina = mercadolivre.item_para_oferta({**ITEM, "id": "MLB777", "title": "Da página"})
    monkeypatch.setattr(ml_pagina, "buscar_ofertas", lambda cats, paginas, inicio: [da_pagina])
    ids = sorted(o.id_produto for o in mercadolivre.buscar_ofertas(ClienteFalso()))
    assert ids == ["MLB1", "MLB777", "MLB900"]


def test_rodizio_de_paginas_de_ofertas(monkeypatch):
    _config(monkeypatch, modo="pagina", paginas_ofertas=1, paginas_ofertas_max=3)
    monkeypatch.setattr(mercadolivre, "_pagina_da_vez", {})
    lidas = []

    def ler(cats, paginas, inicio):
        lidas.append(inicio)
        return [] if inicio == 2 and len(lidas) > 3 else [mercadolivre.item_para_oferta(ITEM)]
    monkeypatch.setattr(ml_pagina, "buscar_ofertas", ler)
    for _ in range(6):
        mercadolivre.buscar_ofertas(ClienteFalso(), {"MLB1384": "Bebês"})
    # 1,2,3 e recomeça; na 2ª volta a página 2 veio vazia -> volta para a 1
    assert lidas == [1, 2, 3, 1, 2, 1]


HTML = """
<div class="poly-card">
  <img class="poly-component__picture" src="https://img/a.jpg">
  <a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-4012345678-fone-_JM?x=1">Fone XYZ</a>
  <s class="andes-money-amount--previous"><span class="andes-money-amount__fraction">1.200</span></s>
  <div class="poly-price__current"><span class="andes-money-amount__fraction">899</span>
    <span class="andes-money-amount__cents">90</span></div>
  <span class="poly-price__discount-polylabel">25% OFF</span>
  <span>Frete grátis</span>
</div>"""


def test_parse_pagina():
    [o] = ml_pagina.parse_pagina(HTML)
    assert o.id_produto == "MLB4012345678"
    assert (o.preco, o.preco_original, o.desconto) == (899.9, 1200.0, 25)
    assert o.url_produto == "https://produto.mercadolivre.com.br/MLB-4012345678-fone-_JM"
    assert o.extra == "🚚 Frete grátis"


def test_bloqueio_lembrado_entre_ciclos(monkeypatch):
    _config(monkeypatch)
    c = ClienteFalso()
    mercadolivre.buscar_ofertas(c, {"MLB1648": "Info"})
    mercadolivre.buscar_ofertas(c, {"MLB1051": "Celulares"})
    assert c.chamadas.count("buscar") == 1  # a busca bloqueada não é tentada de novo


def test_cliente_padrao_e_reaproveitado(monkeypatch):
    monkeypatch.setattr(mercadolivre, "_cliente", None)
    assert mercadolivre.cliente_padrao() is mercadolivre.cliente_padrao()


def test_rodizio_de_subcategorias(monkeypatch):
    _config(monkeypatch, subcategorias_por_busca=2)
    c = ClienteFalso()
    c.filhas = {"MLB1384": ["F1", "F2", "F3"]}
    for _ in range(3):
        mercadolivre.buscar_ofertas(c, {"MLB1384": "Bebês"})
    feitas = [ch.split(":")[1] for ch in c.chamadas if ch.startswith("destaques")]
    assert feitas == ["MLB1384", "F1", "F2", "F3", "MLB1384", "F1"]


def test_subcategoria_sem_ranking_e_pulada(monkeypatch):
    _config(monkeypatch, subcategorias_por_busca=2)

    class Parcial(ClienteFalso):
        def destaques(self, site, cat):
            if cat == "MLB1384":
                raise ErroAPI("GET /highlights respondeu HTTP 404")
            return super().destaques(site, cat)
    c = Parcial()
    c.filhas = {"MLB1384": ["F1"]}
    assert sorted(o.id_produto for o in mercadolivre.buscar_ofertas(c, {"MLB1384": "Bebês"})) == ["MLB1", "MLB900"]


def test_subcategorias_da_api_com_cache():
    from tests.test_mercadolivre import Resp, SessaoFalsa
    s = SessaoFalsa([Resp(200, {"children_categories": [{"id": "MLB1"}, {"id": "MLB2"}]})])
    c = mercadolivre.ClienteML(access_token="T", sessao=s)
    assert c.subcategorias("MLB1384") == ["MLB1", "MLB2"]
    assert c.subcategorias("MLB1384") == ["MLB1", "MLB2"]  # sem nova chamada
    assert len(s.chamadas) == 1
