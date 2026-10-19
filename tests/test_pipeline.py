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
    assert msg.startswith("🔥 *Air Fryer*")  # sem gancho: título em destaque
    assert "De ~R$ 500~ por *R$ 300* 🔻40%" in msg
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
    o.extra = "🚚 Frete grátis · 💠 preço no Pix"
    g = Grupo("mulher", "Mulher", whatsapp=["x"], convite="https://chat.whatsapp.com/ABC",
              ganchos=["ACHADINHO DO DIA"], chamada="💬 Manda pra aquela amiga!")
    linhas = montar_mensagem(o, g).split("\n")
    assert linhas[:3] == ["*ACHADINHO DO DIA*", "", "Kit Banheiro"]
    i = linhas.index("De ~R$ 149,90~ por *R$ 69,90* no Pix 🔻53%")
    assert linhas[i + 1] == "💰 Você economiza *R$ 80*"
    assert linhas[i + 2] == "🚚 Frete grátis"
    assert linhas[-2:] == ["💬 Manda pra aquela amiga!", "👉 https://chat.whatsapp.com/ABC"]


def test_chamada_padrao_e_ganchos_em_rodizio():
    from ofertas import formatter
    from ofertas.models import Grupo
    g = Grupo("carro", "Carro", convite="https://chat.whatsapp.com/X", ganchos=["A", "B", "C"])
    vistos = [formatter.montar_mensagem(_o("1", "Cera", 10.0, 20.0), g).split("\n")[0] for _ in range(6)]
    assert sorted(set(vistos)) == ["*A*", "*B*", "*C*"]
    assert vistos[:3] != vistos[0:1] * 3 and vistos[:3] == vistos[3:]  # rodízio, sem repetir em seguida
    assert formatter.CHAMADA_PADRAO in formatter.montar_mensagem(_o("1", "Cera", 10.0, 20.0), g)


def test_titulo_curto():
    from ofertas.formatter import titulo_curto
    assert titulo_curto("Rádio Automotivo Pioneer Mvh-145br Bluetooth Usb Aux Rádio Fm Android Iphone 1 Din") \
        == "Rádio Automotivo Pioneer Mvh-145br Bluetooth Usb Aux Fm"
    assert titulo_curto("Kit 4 Litros Oleo (Original) Maxi Performace 5w40 para") == "Kit 4 Litros Oleo Maxi Performace 5w40"
    assert titulo_curto("Fone") == "Fone"


def test_preco_curto():
    from ofertas.formatter import preco_curto
    assert preco_curto(281.0) == "R$ 281"
    assert preco_curto(1299.0) == "R$ 1.299"
    assert preco_curto(69.9) == "R$ 69,90"


def test_sem_preco_antigo_nao_mostra_economia_e_sem_convite_nao_mostra_rodape():
    from ofertas.models import Grupo
    msg = montar_mensagem(_o("1", "Fone", 50.0, None), Grupo("g", "G"))
    assert "economiza" not in msg
    assert "Manda" not in msg
    assert msg.endswith("🛒 https://ml/1")


def test_palavra_bloqueada_compara_palavra_inteira(monkeypatch):
    from ofertas import pipeline
    monkeypatch.setattr(pipeline.config, "palavras_bloqueadas", ["pet", "lente", "club 6", "cão"])
    assert pipeline.tem_palavra_bloqueada("Cama Pet Grande")
    assert pipeline.tem_palavra_bloqueada("Lenço Para Limpeza Lente Óculos")
    assert pipeline.tem_palavra_bloqueada("Club 6 Voyage Desodorante Colônia")
    assert pipeline.tem_palavra_bloqueada("Ração Para Cão Adulto")
    assert not pipeline.tem_palavra_bloqueada("Tapete De Atividades Bebê")
    assert not pipeline.tem_palavra_bloqueada("Sérum Excelente Hidratação")
    assert not pipeline.tem_palavra_bloqueada("Kit Coleção Proteção Solar")


def test_bloquear_por_grupo(monkeypatch):
    from ofertas import config as cfg
    from ofertas import pipeline
    monkeypatch.setattr(pipeline.config, "palavras_bloqueadas", ["masculino"])
    monkeypatch.setattr(pipeline.config, "desconto_minimo", 0)
    monkeypatch.setattr(pipeline.db, "ja_enviada", lambda *a, **k: False)
    ofertas = [Oferta("x", "1", "Molinete de Pesca", "u", 10, 20),
               Oferta("x", "2", "Tênis Masculino Corrida", "u", 10, 20),
               Oferta("x", "3", "Legging Fitness", "u", 10, 20)]
    assert [o.id_produto for o in pipeline.filtrar(ofertas, "fit", ["pesca"])] == ["3"]
    assert [o.id_produto for o in pipeline.filtrar(ofertas, "outro")] == ["1", "3"]
    [g] = cfg.ler_grupos({"fit": {"categorias": ["MLB1276"], "bloquear": ["pesca", " bicicleta "]}})
    assert g.bloquear == ["pesca", "bicicleta"]


def test_sequencia_das_lojas_pela_proporcao():
    from ofertas.models import Grupo
    seq = lambda ml, sh: pipeline.sequencia_lojas(Grupo("g", "G", peso_ml=ml, peso_shopee=sh))
    assert seq(1, 1) == ["ml", "shopee"]
    assert seq(3, 1) == ["ml", "ml", "ml", "shopee"]
    assert seq(3, 1).count("shopee") == 1
    assert seq(2, 0) == ["ml", "ml"]
    assert seq(0, 0) == ["ml", "shopee"]
    s = seq(2, 3)
    assert s.count("ml") == 2 and s.count("shopee") == 3 and "shopee, shopee, shopee" not in ", ".join(s)


def test_log_mostra_motivo_do_descarte(monkeypatch):
    from collections import Counter
    monkeypatch.setattr(pipeline.db, "ja_enviada", lambda uid, dias, grupo, titulo="": uid == "mercadolivre:3")
    monkeypatch.setattr(config, "desconto_minimo", 25)
    monkeypatch.setattr(config, "preco_minimo", 0)
    monkeypatch.setattr(config, "preco_maximo", 0)
    monkeypatch.setattr(config, "palavras_bloqueadas", ["capinha"])
    ofertas = [_o("1", "Fone", 50, 100), _o("2", "Mouse", 90, 100), _o("3", "Teclado", 10, 100),
               _o("4", "Capinha iPhone", 5, 50), _o("5", "Cabo", 95, 100)]
    motivos = Counter()
    boas = pipeline.filtrar(ofertas, "g", motivos=motivos)
    assert pipeline._resumo(ofertas, boas, motivos) == \
        "5 coletadas, 1 novas nos filtros (fora: 2 desconto < 25%, 1 já enviadas, 1 palavra bloqueada)"


def test_mensagem_mostra_a_loja_antes_do_link():
    assert montar_mensagem(_o("1", "Fone", 50.0, 100.0)).endswith("💛 Mercado Livre\n🛒 https://ml/1")
