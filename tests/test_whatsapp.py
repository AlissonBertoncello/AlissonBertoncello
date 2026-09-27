import pytest

from ofertas import evolution
from ofertas.destinos.whatsapp import WhatsApp
from ofertas.evolution import ErroWhatsApp, Evolution
from ofertas.models import Grupo, Oferta


class Resp:
    def __init__(self, status, dados=None):
        self.status_code = status
        self._dados = dados
        self.content = b"x" if dados is not None else b""
        self.text = str(dados)

    def json(self):
        return self._dados


class SessaoFalsa:
    """Responde por (método, caminho); registra as chamadas."""
    def __init__(self, rotas):
        self.headers = {}
        self.rotas = rotas
        self.chamadas = []

    def request(self, metodo, url, **kw):
        caminho = url.split("8080", 1)[1]
        self.chamadas.append((metodo, caminho, kw))
        r = self.rotas.get((metodo, caminho))
        return r(kw) if callable(r) else (r or Resp(404, {"message": "not found"}))

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


GRUPOS = [{"id": "111@g.us", "subject": "Ofertas Casa & Info"},
          {"id": "222@g.us", "subject": "Ofertas Mamãe e Bebê"}]


def _evo(rotas):
    s = SessaoFalsa({("GET", "/group/fetchAllGroups/bot"): Resp(200, GRUPOS), **rotas})
    return Evolution("http://localhost:8080", "KEY", "bot", sessao=s), s


def _oferta(imagem="https://img/1.jpg"):
    return Oferta("mercadolivre", "MLB1", "Fone", "https://ml/1", 50, 100, imagem=imagem,
                  url_afiliado="https://meli.la/x")


def test_id_do_grupo_por_nome_sem_diferenciar_maiusculas():
    evo, s = _evo({})
    assert evo.id_do_grupo("ofertas casa & info") == "111@g.us"
    assert evo.id_do_grupo("Ofertas Mamãe e Bebê") == "222@g.us"
    assert sum(1 for c in s.chamadas if "fetchAllGroups" in c[1]) == 1  # lista em cache
    assert s.chamadas[0][2]["params"] == {"getParticipants": "false"}
    assert s.headers["apikey"] == "KEY"


def test_id_direto_e_grupo_inexistente():
    evo, _ = _evo({})
    assert evo.id_do_grupo("999@g.us") == "999@g.us"
    with pytest.raises(ErroWhatsApp, match="não encontrado"):
        evo.id_do_grupo("Grupo que não existe")


def test_envia_foto_com_legenda():
    evo, s = _evo({("POST", "/message/sendMedia/bot"): Resp(201, {"key": {}})})
    grupo = Grupo("casa", "Casa", {"X": "x"}, whatsapp="Ofertas Casa & Info")
    WhatsApp(evo).enviar(_oferta(), "🔥 *Fone*", grupo)
    metodo, caminho, kw = s.chamadas[-1]
    assert (metodo, caminho) == ("POST", "/message/sendMedia/bot")
    assert kw["json"]["number"] == "111@g.us"
    assert kw["json"]["mediatype"] == "image"
    assert kw["json"]["media"] == "https://img/1.jpg"
    assert kw["json"]["caption"] == "🔥 *Fone*"


def test_foto_recusada_cai_para_texto():
    evo, s = _evo({("POST", "/message/sendMedia/bot"): Resp(400, {"message": "bad media"}),
                   ("POST", "/message/sendText/bot"): Resp(201, {"key": {}})})
    WhatsApp(evo).enviar(_oferta(), "msg", Grupo("c", "C", whatsapp="111@g.us"))
    assert s.chamadas[-1][1] == "/message/sendText/bot"
    assert s.chamadas[-1][2]["json"] == {"number": "111@g.us", "text": "msg",
                                         "linkPreview": True, "delay": 1200}


def test_sem_imagem_envia_texto():
    evo, s = _evo({("POST", "/message/sendText/bot"): Resp(201, {})})
    WhatsApp(evo).enviar(_oferta(imagem=None), "msg", Grupo("c", "C", whatsapp="111@g.us"))
    assert [c[1] for c in s.chamadas] == ["/message/sendText/bot"]


def test_falha_no_envio_propaga_erro():
    evo, _ = _evo({("POST", "/message/sendText/bot"): Resp(500, {"message": "down"})})
    with pytest.raises(ErroWhatsApp, match="HTTP 500"):
        WhatsApp(evo).enviar(_oferta(imagem=None), "msg", Grupo("c", "C", whatsapp="111@g.us"))


def test_preparar_exige_conexao_e_grupos(monkeypatch):
    estado = {"s": "close"}
    evo, _ = _evo({("GET", "/instance/connectionState/bot"):
                   lambda kw: Resp(200, {"instance": {"state": estado["s"]}})})
    monkeypatch.setattr(evo, "subir", lambda: None)
    wa = WhatsApp(evo)
    ok = [Grupo("c", "C", whatsapp="Ofertas Casa & Info")]
    with pytest.raises(ErroWhatsApp, match="LOGIN_WHATSAPP"):
        wa.preparar(ok)
    estado["s"] = "open"
    wa.preparar(ok)
    with pytest.raises(ErroWhatsApp, match="não tem 'whatsapp:'"):
        wa.preparar([Grupo("b", "B")])


def test_qr_cria_instancia_quando_nao_existe():
    evo, s = _evo({("POST", "/instance/create"):
                   Resp(201, {"instance": {}, "qrcode": {"base64": "data:image/png;base64,AAA"}})})
    assert evo.qr_code() == "data:image/png;base64,AAA"
    assert s.chamadas[-1][2]["json"]["integration"] == "WHATSAPP-BAILEYS"


def test_qr_de_instancia_existente():
    evo, _ = _evo({("GET", "/instance/connectionState/bot"): Resp(200, {"instance": {"state": "close"}}),
                   ("GET", "/instance/connect/bot"): Resp(200, {"base64": "data:image/png;base64,BBB"})})
    assert evo.qr_code() == "data:image/png;base64,BBB"


def test_garantir_api_key_grava_no_env(monkeypatch, tmp_path):
    monkeypatch.setattr(evolution, "BASE_DIR", tmp_path)
    monkeypatch.setattr(evolution.config, "evolution_api_key", "")
    chave = evolution.garantir_api_key()
    assert len(chave) == 32
    assert f"EVOLUTION_API_KEY={chave}" in (tmp_path / ".env").read_text()
    assert evolution.garantir_api_key() == chave  # não gera outra


def test_login_sem_qr_explica_o_motivo(monkeypatch):
    class EvoFalsa:
        def subir(self):
            pass

        def estado(self):
            return "connecting"

        def qr_code(self):
            return None
    monkeypatch.setattr(evolution, "Evolution", EvoFalsa)
    monkeypatch.setattr(evolution.time, "sleep", lambda s: None)
    with pytest.raises(ErroWhatsApp, match="não conseguiu gerar o QR Code"):
        evolution.whatsapp_login(espera_s=0.05)
