import pytest

from ofertas import afiliado_ml, pipeline
from ofertas.afiliado_ml import ErroAfiliado, criar_links, extrair_id
from ofertas.models import Oferta


class PaginaFalsa:
    def __init__(self, resposta):
        self.resposta = resposta
        self.args = None

    def evaluate(self, js, args):
        self.args = args
        return self.resposta


def test_extrair_id():
    assert extrair_id("https://produto.mercadolivre.com.br/MLB-4012345678-fone-_JM") == "MLB4012345678"
    assert extrair_id("https://www.mercadolivre.com.br/fone/p/MLB19876543") == "MLB19876543"
    assert extrair_id("https://www.mercadolivre.com.br/ofertas") is None


def test_criar_links_ok():
    page = PaginaFalsa({"http": 200, "dados": {"urls": [
        {"short_url": "https://meli.la/1"}, {"short_url": "https://meli.la/2"}]}})
    assert criar_links(page, ["u1", "u2"], "minhatag") == ["https://meli.la/1", "https://meli.la/2"]
    assert page.args["urls"] == ["u1", "u2"] and page.args["tag"] == "minhatag"


def test_criar_links_sessao_expirada():
    with pytest.raises(ErroAfiliado, match="ml-login"):
        criar_links(PaginaFalsa({"http": 401, "texto": ""}), ["u1"], "t")


def test_criar_links_incompleto():
    page = PaginaFalsa({"http": 200, "dados": {"urls": [{"short_url": "https://meli.la/1"}]}})
    with pytest.raises(ErroAfiliado, match="1 links para 2"):
        criar_links(page, ["u1", "u2"], "t")


def test_sem_etiqueta(monkeypatch):
    monkeypatch.setattr(afiliado_ml.config, "ml_etiqueta", "")
    with pytest.raises(ErroAfiliado, match="ML_ETIQUETA"):
        afiliado_ml.gerar_links_afiliado([Oferta("mercadolivre", "1", "x", "https://ml/1")])


def test_pipeline_descarta_sem_link(monkeypatch):
    a = Oferta("mercadolivre", "1", "Fone", "https://ml/1")
    b = Oferta("mercadolivre", "2", "Mouse", "https://ml/2")

    def gerar(ofertas):
        ofertas[0].url_afiliado = "https://meli.la/1"  # só o primeiro sai
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    assert pipeline.com_link_afiliado([a, b]) == [a]


def test_pipeline_falha_linkbuilder_nao_envia(monkeypatch):
    def gerar(ofertas):
        raise ErroAfiliado("Sessão do ML expirou")
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    assert pipeline.com_link_afiliado([Oferta("mercadolivre", "1", "x", "https://ml/1")]) == []



def test_ciclo_usa_reserva_quando_falta_link(monkeypatch):
    ofertas = [Oferta("mercadolivre", str(i), f"Produto {i}", f"https://ml/{i}", 10, 100 - i)
               for i in range(3)]
    monkeypatch.setattr(pipeline, "coletar", lambda categorias=None: ofertas)
    monkeypatch.setattr(pipeline, "filtrar", lambda o: o)
    monkeypatch.setattr(pipeline.config, "max_posts_por_ciclo", 1)
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)

    def gerar(lista):  # a melhor oferta (id 0) fica sem link
        for o in lista:
            if o.id_produto != "0":
                o.url_afiliado = f"https://meli.la/{o.id_produto}"
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)

    enviadas = []

    class Destino:
        nome = "console"

        def enviar(self, o, msg):
            enviadas.append(o)
    assert pipeline.executar_ciclo(Destino(), registrar=False) == 1
    assert enviadas[0].url_afiliado == "https://meli.la/1"


def test_ciclo_sem_link_nao_envia_nada(monkeypatch):
    monkeypatch.setattr(pipeline, "coletar",
                        lambda categorias=None: [Oferta("mercadolivre", "1", "x", "https://ml/1", 10, 100)])
    monkeypatch.setattr(pipeline, "filtrar", lambda o: o)
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)

    def gerar(lista):
        raise ErroAfiliado("Sessão do ML não encontrada")
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)

    class Destino:
        nome = "console"

        def enviar(self, o, msg):
            raise AssertionError("não deveria enviar oferta sem link de afiliado")
    assert pipeline.executar_ciclo(Destino(), registrar=False) == 0
