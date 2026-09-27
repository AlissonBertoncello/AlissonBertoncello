from ofertas.sources.mercadolivre import ClienteML, ErroAPI, item_para_oferta

ITEM = {
    "id": "MLB123456789",
    "title": " Fone Bluetooth XYZ ",
    "permalink": "https://produto.mercadolivre.com.br/MLB-123456789-fone#pos=1",
    "price": 99.9,
    "original_price": 199.9,
    "thumbnail": "http://http2.mlstatic.com/D_123-I.jpg",
    "shipping": {"free_shipping": True},
    "official_store_id": 42,
}


class Resp:
    def __init__(self, status, dados):
        self.status_code = status
        self._dados = dados
        self.text = str(dados)

    def json(self):
        return self._dados


class SessaoFalsa:
    def __init__(self, respostas):
        self.headers = {}
        self.respostas = list(respostas)
        self.chamadas = []

    def post(self, url, **kw):
        self.chamadas.append(("POST", url, kw))
        return self.respostas.pop(0)

    def get(self, url, **kw):
        self.chamadas.append(("GET", url, kw))
        return self.respostas.pop(0)


def test_item_para_oferta():
    o = item_para_oferta(ITEM)
    assert o.id_produto == "MLB123456789"
    assert o.titulo == "Fone Bluetooth XYZ"
    assert o.url_produto == "https://produto.mercadolivre.com.br/MLB-123456789-fone"
    assert o.desconto == 50
    assert o.imagem == "https://http2.mlstatic.com/D_123-O.jpg"
    assert "Frete grátis" in o.extra and "Loja oficial" in o.extra


def test_item_usa_sale_price():
    o = item_para_oferta({**ITEM, "sale_price": {"amount": 80, "regular_amount": 160}})
    assert (o.preco, o.preco_original, o.desconto) == (80.0, 160.0, 50)


def test_item_incompleto_ignorado():
    assert item_para_oferta({"id": "MLB1"}) is None


def test_busca_gera_token_e_reusa():
    s = SessaoFalsa([
        Resp(200, {"access_token": "TOK", "expires_in": 21600}),
        Resp(200, {"results": [ITEM]}),
        Resp(200, {"results": []}),
    ])
    c = ClienteML("id", "secret", sessao=s)
    assert c.buscar("MLB", q="fone", limite=999) == [ITEM]
    c.buscar("MLB", categoria="MLB1648")
    assert [m for m, *_ in s.chamadas] == ["POST", "GET", "GET"]
    _, url, kw = s.chamadas[1]
    assert url.endswith("/sites/MLB/search")
    assert kw["params"] == {"limit": 50, "q": "fone"}
    assert kw["headers"]["Authorization"] == "Bearer TOK"


def test_token_fixo_nao_chama_oauth():
    s = SessaoFalsa([Resp(200, {"results": []})])
    ClienteML(access_token="FIXO", sessao=s).buscar("MLB", q="x")
    assert s.chamadas[0][0] == "GET"
    assert s.chamadas[0][2]["headers"]["Authorization"] == "Bearer FIXO"


def test_401_renova_token():
    s = SessaoFalsa([
        Resp(200, {"access_token": "A", "expires_in": 21600}),
        Resp(401, {}),
        Resp(200, {"access_token": "B", "expires_in": 21600}),
        Resp(200, {"results": [ITEM]}),
    ])
    assert ClienteML("id", "secret", sessao=s).buscar("MLB", q="x") == [ITEM]
    assert s.chamadas[-1][2]["headers"]["Authorization"] == "Bearer B"


def test_erro_http_vira_erroapi():
    s = SessaoFalsa([Resp(403, {"message": "forbidden"})])
    try:
        ClienteML(access_token="T", sessao=s).buscar("MLB", q="x")
    except ErroAPI as e:
        assert "403" in str(e)
    else:
        raise AssertionError("esperava ErroAPI")


def test_sem_credenciais():
    try:
        ClienteML(sessao=SessaoFalsa([])).token()
    except ErroAPI as e:
        assert "ML_CLIENT_ID" in str(e)
    else:
        raise AssertionError("esperava ErroAPI")


def test_converter_usa_api_e_gera_link(monkeypatch):
    from ofertas.sources import mercadolivre

    def gerar(ofertas):
        for o in ofertas:
            o.url_afiliado = "https://meli.la/abc"
    monkeypatch.setattr(mercadolivre, "gerar_links_afiliado", gerar)
    s = SessaoFalsa([Resp(200, ITEM)])
    o = mercadolivre.converter("https://produto.mercadolivre.com.br/MLB-123456789-fone?x=1",
                               ClienteML(access_token="T", sessao=s))
    assert s.chamadas[0][1].endswith("/items/MLB123456789")
    assert o.titulo == "Fone Bluetooth XYZ"
    assert o.link == "https://meli.la/abc"


def test_token_reaproveitado_entre_buscas():
    s = SessaoFalsa([
        Resp(200, {"access_token": "TOK", "expires_in": 21600}),
        Resp(200, {"results": []}),
        Resp(200, {"results": []}),
        Resp(200, {"results": []}),
    ])
    c = ClienteML("id", "secret", sessao=s)
    for q in ("a", "b", "c"):
        c.buscar("MLB", q=q)
    assert [m for m, *_ in s.chamadas].count("POST") == 1
