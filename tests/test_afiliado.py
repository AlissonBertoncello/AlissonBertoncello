import pytest

from ofertas import afiliado_ml, pipeline
from ofertas.afiliado_ml import ErroAfiliado, criar_links, extrair_id
from ofertas.models import Grupo, Oferta


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




def _ciclo(monkeypatch, ofertas_por_cat, gerar):
    """Prepara executar_ciclo com coleta e Linkbuilder falsos; devolve a lista de envios."""
    monkeypatch.setattr(pipeline, "coletar", lambda cats: list(ofertas_por_cat[next(iter(cats))]))
    monkeypatch.setattr(pipeline, "filtrar", lambda o, grupo: o)
    monkeypatch.setattr(pipeline.config, "max_posts_por_ciclo", 1)
    monkeypatch.setattr(pipeline, "dentro_do_horario", lambda: True)
    monkeypatch.setattr(pipeline.afiliado_ml, "gerar_links_afiliado", gerar)
    monkeypatch.setattr(pipeline, "_proxima", {})
    envios = []

    class Destino:
        nome = "console"

        def enviar(self, o, msg, grupo):
            envios.append((grupo.chave, o.id_produto))
    return Destino(), envios


def _todas_com_link(lista):
    for o in lista:
        o.url_afiliado = f"https://meli.la/{o.id_produto}"


def _of(id_, desconto=50):
    return Oferta("mercadolivre", id_, f"Produto {id_}", f"https://ml/{id_}", 100 - desconto, 100)


def test_ciclo_usa_reserva_quando_falta_link(monkeypatch):
    def gerar(lista):  # a melhor oferta (A) fica sem link
        for o in lista:
            if o.id_produto != "A":
                o.url_afiliado = "https://meli.la/" + o.id_produto
    destino, envios = _ciclo(monkeypatch, {"C1": [_of("A", 60), _of("B", 50)]}, gerar)
    grupo = Grupo("g", "G", {"C1": "Cat 1"})
    assert pipeline.executar_ciclo(destino, [grupo], registrar=False) == 1
    assert envios == [("g", "B")]


def test_ciclo_sem_link_nao_envia_nada(monkeypatch):
    def gerar(lista):
        raise ErroAfiliado("Sessão do ML não encontrada")
    destino, envios = _ciclo(monkeypatch, {"C1": [_of("A")]}, gerar)
    assert pipeline.executar_ciclo(destino, [Grupo("g", "G", {"C1": "x"})], registrar=False) == 0
    assert envios == []


def test_grupos_recebem_cada_um_sua_oferta_em_um_lote(monkeypatch):
    lotes = []

    def gerar(lista):
        lotes.append(len(lista))
        _todas_com_link(lista)
    destino, envios = _ciclo(monkeypatch, {"CASA": [_of("casa1")], "BEBE": [_of("bebe1")]}, gerar)
    grupos = [Grupo("casa", "Casa", {"CASA": "Casa"}), Grupo("bebe", "Bebê", {"BEBE": "Bebês"})]
    assert pipeline.executar_ciclo(destino, grupos, registrar=False) == 2
    assert envios == [("casa", "casa1"), ("bebe", "bebe1")]
    assert lotes == [2]  # um único lote no Linkbuilder para os dois grupos


def test_rodizio_alterna_categorias(monkeypatch):
    destino, envios = _ciclo(monkeypatch, {"CASA": [_of("c")], "INFO": [_of("i")]}, _todas_com_link)
    grupo = Grupo("g", "G", {"CASA": "Casa", "INFO": "Informática"})
    for _ in range(3):
        pipeline.executar_ciclo(destino, [grupo], registrar=False)
    assert [i for _, i in envios] == ["c", "i", "c"]


def test_rodizio_pula_categoria_sem_oferta(monkeypatch):
    destino, envios = _ciclo(monkeypatch, {"CASA": [], "INFO": [_of("i")]}, _todas_com_link)
    grupo = Grupo("g", "G", {"CASA": "Casa", "INFO": "Informática"})
    pipeline.executar_ciclo(destino, [grupo], registrar=False)
    assert envios == [("g", "i")]
