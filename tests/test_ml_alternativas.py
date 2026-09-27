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
        self.chamadas = []

    def buscar(self, site, **kw):
        self.chamadas.append("buscar")
        if self.busca_403:
            raise ErroAPI("GET /sites/MLB/search respondeu HTTP 403: forbidden")
        return [ITEM]

    def destaques(self, site, cat):
        self.chamadas.append("destaques")
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
    assert "catalogo" in c.chamadas and "destaques" in c.chamadas


def test_busca_liberada_usa_busca(monkeypatch):
    _config(monkeypatch)
    c = ClienteFalso(busca_403=False)
    assert [o.id_produto for o in mercadolivre.buscar_ofertas(c)] == ["MLB1"]
    assert "destaques" not in c.chamadas


def test_auto_cai_para_pagina(monkeypatch):
    _config(monkeypatch, modo="auto")

    class SemNada(ClienteFalso):
        def destaques(self, site, cat):
            raise ErroAPI("HTTP 403")
    monkeypatch.setattr(ml_pagina, "buscar_ofertas",
                        lambda cats, paginas: [mercadolivre.item_para_oferta(ITEM)])
    assert [o.id_produto for o in mercadolivre.buscar_ofertas(SemNada())] == ["MLB1"]


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
