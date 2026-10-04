import hashlib
import json

import pytest

from ofertas import pipeline
from ofertas.models import Grupo, Oferta
from ofertas.sources import shopee
from ofertas.sources.shopee import ErroShopee

NODE = {"itemId": 123, "productName": " Sérum Vitamina C 30ml ", "priceMin": "29.90",
        "priceDiscountRate": 50, "imageUrl": "https://cf.shopee/img.jpg",
        "offerLink": "https://s.shopee.com.br/abc", "productLink": "https://shopee.com.br/p/123",
        "sales": 2300, "ratingStar": "4.87", "shopName": "Loja X"}


class Resp:
    def __init__(self, status, dados):
        self.status_code = status
        self._dados = dados
        self.text = json.dumps(dados)

    def json(self):
        return self._dados


class SessaoFalsa:
    def __init__(self, resp):
        self.resp = resp
        self.chamadas = []

    def post(self, url, data, headers, timeout):
        self.chamadas.append((url, data, headers))
        return self.resp


@pytest.fixture
def credenciais(monkeypatch):
    monkeypatch.setattr(shopee.config, "shopee_app_id", "APP")
    monkeypatch.setattr(shopee.config, "shopee_app_secret", "SEGREDO")
    monkeypatch.setattr(shopee.config, "fonte_shopee", {"ativa": True, "limite_por_busca": 20, "ordenacao": 2})


def test_node_para_oferta():
    o = shopee.node_para_oferta(NODE)
    assert (o.plataforma, o.id_produto, o.titulo) == ("shopee", "123", "Sérum Vitamina C 30ml")
    assert o.url_afiliado == "https://s.shopee.com.br/abc"  # link de afiliado já vem pronto
    assert (o.preco, o.preco_original, o.desconto) == (29.9, 59.8, 50)
    assert o.extra == "⭐ 4.9 · 2.300 vendidos"


def test_node_sem_link_de_afiliado_e_ignorado():
    assert shopee.node_para_oferta({**NODE, "offerLink": ""}) is None


def test_assinatura():
    esperado = hashlib.sha256(b"APP1700000000{}SEGREDO").hexdigest()
    assert shopee.assinar("APP", "SEGREDO", "{}", "1700000000") == \
        f"SHA256 Credential=APP, Timestamp=1700000000, Signature={esperado}"


def test_buscar_monta_query_e_assina(credenciais):
    s = SessaoFalsa(Resp(200, {"data": {"productOfferV2": {"nodes": [NODE]}}}))
    [o] = shopee.buscar('vestido "midi"', 10, sessao=s)
    url, data, headers = s.chamadas[0]
    assert url == shopee.ENDPOINT
    query = json.loads(data)["query"]
    assert 'keyword:"vestido \\"midi\\""' in query and "sortType:2" in query and "limit:10" in query
    assert headers["Authorization"].startswith("SHA256 Credential=APP, Timestamp=")
    assert o.id_produto == "123"


def test_erros(credenciais):
    with pytest.raises(ErroShopee, match="HTTP 403"):
        shopee.buscar("x", sessao=SessaoFalsa(Resp(403, {"message": "forbidden"})))
    with pytest.raises(ErroShopee, match="Shopee API"):
        shopee.buscar("x", sessao=SessaoFalsa(Resp(200, {"errors": [{"message": "invalid signature"}]})))


def test_sem_credenciais(monkeypatch):
    monkeypatch.setattr(shopee.config, "shopee_app_id", "")
    with pytest.raises(ErroShopee, match="SHOPEE_APP_ID"):
        shopee.chamar("{}")


# ── rodízio entre as lojas ──────────────────────────────────────────

def _of(plataforma, id_, desconto=50):
    o = Oferta(plataforma, id_, f"Produto {plataforma} {id_}", f"https://x/{id_}", 100 - desconto, 100)
    if plataforma == "shopee":
        o.url_afiliado = f"https://s.shopee/{id_}"
    return o


@pytest.fixture
def ciclo(monkeypatch, credenciais):
    for nome in ("_proxima", "_proxima_shopee", "_loja_da_vez"):
        monkeypatch.setattr(pipeline, nome, {})
    monkeypatch.setattr(pipeline, "_avisou_shopee", set())
    monkeypatch.setattr(pipeline.config, "fonte_ml", {"ativa": True})
    monkeypatch.setattr(pipeline.config, "max_posts_por_ciclo", 1)
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)
    monkeypatch.setattr(pipeline, "filtrar", lambda o, grupo: o)
    gerados = []

    def gerar(lista):
        gerados.append([o.plataforma for o in lista])
        for o in lista:
            o.url_afiliado = "https://meli.la/" + o.id_produto
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    envios = []

    class Destino:
        nome = "console"

        def enviar(self, o, msg, grupo):
            envios.append((o.plataforma, o.id_produto, msg))
    return Destino(), envios, gerados


def test_alterna_mercado_livre_e_shopee(monkeypatch, ciclo):
    destino, envios, gerados = ciclo
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("mercadolivre", next(iter(cats)))])
    buscas = []
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: buscas.append(termo) or [_of("shopee", termo)])
    g = Grupo("g", "G", {"C1": "Cat 1", "C2": "Cat 2"}, shopee=["fralda", "body bebê"])
    for _ in range(4):
        pipeline.executar_ciclo(destino, [g], registrar=False)
    assert [(p, i) for p, i, _ in envios] == [("mercadolivre", "C1"), ("shopee", "fralda"),
                                              ("mercadolivre", "C2"), ("shopee", "body bebê")]
    assert "🧡 Shopee" in envios[1][2]
    # o Linkbuilder do ML nunca recebe produto da Shopee
    assert all(set(lote) == {"mercadolivre"} for lote in gerados)


def test_sem_credenciais_usa_so_mercado_livre(monkeypatch, ciclo, caplog):
    destino, envios, _ = ciclo
    monkeypatch.setattr(pipeline.config, "shopee_app_id", "")
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("mercadolivre", next(iter(cats)))])
    g = Grupo("g", "G", {"C1": "Cat 1", "C2": "Cat 2"}, shopee=["fralda"])
    for _ in range(3):
        pipeline.executar_ciclo(destino, [g], registrar=False)
    assert [p for p, _, _ in envios] == ["mercadolivre"] * 3
    assert sum("sem SHOPEE_APP_ID" in r.message for r in caplog.records) == 1  # avisa uma vez só


def test_shopee_sem_oferta_cai_para_mercado_livre(monkeypatch, ciclo):
    destino, envios, _ = ciclo
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("mercadolivre", next(iter(cats)))])
    buscas = []
    monkeypatch.setattr(pipeline.shopee, "buscar", lambda termo: buscas.append(termo) or [])
    g = Grupo("g", "G", {"C1": "Cat 1"}, shopee=["a", "b", "c", "d", "e"])
    pipeline.executar_ciclo(destino, [g], registrar=False)  # vez do ML
    pipeline.executar_ciclo(destino, [g], registrar=False)  # vez da Shopee: vazia -> ML
    assert [p for p, _, _ in envios] == ["mercadolivre", "mercadolivre"]
    assert buscas == ["a", "b", "c"]  # tenta no máximo 3 palavras por ciclo


def test_erro_na_shopee_nao_derruba_o_ciclo(monkeypatch, ciclo):
    destino, envios, _ = ciclo
    monkeypatch.setattr(pipeline, "coletar", lambda cats: [_of("mercadolivre", "C1")])

    def falha(termo):
        raise ErroShopee("Shopee respondeu HTTP 500")
    monkeypatch.setattr(pipeline.shopee, "buscar", falha)
    g = Grupo("g", "G", {"C1": "Cat 1"}, shopee=["fralda"])
    pipeline._loja_da_vez["g"] = 1  # começa pela Shopee
    assert pipeline.executar_ciclo(destino, [g], registrar=False) == 1
    assert envios[0][0] == "mercadolivre"


def test_grupo_so_com_shopee_e_valido():
    from ofertas import config as cfg
    [g] = cfg.ler_grupos({"x": {"shopee": ["fralda", " "]}})
    assert g.categorias == {} and g.shopee == ["fralda"]
