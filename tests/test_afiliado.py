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


def test_previa_console_mantem_sem_link(monkeypatch):
    def gerar(ofertas):
        raise ErroAfiliado("Sessão do ML não encontrada")
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    o = Oferta("mercadolivre", "1", "x", "https://ml/1")
    assert pipeline.com_link_afiliado([o], descartar=False) == [o]
