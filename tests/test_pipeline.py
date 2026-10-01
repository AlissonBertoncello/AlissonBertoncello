from ofertas import pipeline
from ofertas.config import config
from ofertas.formatter import montar_mensagem, preco_br
from ofertas.models import Oferta


def _o(id_, titulo, preco, original):
    return Oferta("mercadolivre", id_, titulo, f"https://ml/{id_}", preco, original)


def test_preco_br():
    assert preco_br(1234.5) == "R$ 1.234,50"


def test_mensagem_whatsapp():
    msg = montar_mensagem(_o("1", "Air Fryer", 300.0, 500.0))
    assert "*Air Fryer*" in msg
    assert "~R$ 500,00~" in msg
    assert "*R$ 300,00*" in msg and "-40%" in msg
    assert msg.endswith("🛒 https://ml/1")


def test_mensagem_prefere_link_afiliado():
    o = _o("1", "Fone", 50.0, 100.0)
    o.url_afiliado = "https://meli.la/xyz"
    assert montar_mensagem(o).endswith("🛒 https://meli.la/xyz")


def test_filtrar(monkeypatch):
    monkeypatch.setattr(pipeline.db, "ja_enviada", lambda uid, dias, grupo, titulo="": uid == "mercadolivre:3")
    monkeypatch.setattr(config, "desconto_minimo", 25)
    monkeypatch.setattr(config, "preco_minimo", 0)
    monkeypatch.setattr(config, "preco_maximo", 0)
    monkeypatch.setattr(config, "palavras_bloqueadas", ["capinha"])
    ofertas = [
        _o("1", "Fone", 50, 100),         # ok
        _o("2", "Mouse", 90, 100),        # desconto baixo
        _o("3", "Teclado", 10, 100),      # já enviada
        _o("4", "Capinha iPhone", 5, 50),  # bloqueada
    ]
    assert [o.id_produto for o in pipeline.filtrar(ofertas, "g")] == ["1"]


def test_escolher_pula_variacoes():
    ofertas = [
        _o("1", "Tênis Nike Air Max 90 Preto", 100, 300),
        _o("2", "Tênis Nike Air Max 90 Branco", 100, 250),
        _o("3", "Panela Tramontina", 50, 100),
    ]
    assert [o.id_produto for o in pipeline.escolher(ofertas, 3)] == ["1", "3"]


def test_mensagem_com_economia_e_convite():
    from ofertas.models import Grupo
    o = _o("1", "Kit Banheiro", 69.90, 149.90)
    o.extra = "🚚 Frete grátis"
    g = Grupo("mulher", "Mulher", whatsapp="x", convite="https://chat.whatsapp.com/ABC")
    linhas = montar_mensagem(o, g).split("\n")
    i = linhas.index("✅ Por: *R$ 69,90*  🔻 *-53%*")
    assert linhas[i + 1] == "💰 Você economiza *R$ 80,00*"
    assert linhas[i + 2] == "🚚 Frete grátis"
    assert linhas[-2:] == ["💬 Envie essa oferta para uma amiga!", "👉 https://chat.whatsapp.com/ABC"]


def test_sem_preco_antigo_nao_mostra_economia_e_sem_convite_nao_mostra_rodape():
    from ofertas.models import Grupo
    msg = montar_mensagem(_o("1", "Fone", 50.0, None), Grupo("g", "G"))
    assert "economiza" not in msg
    assert "amiga" not in msg
    assert msg.endswith("🛒 https://ml/1")
