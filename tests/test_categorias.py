from ofertas import config as cfg
from ofertas import db
from ofertas.models import Oferta


def test_ler_grupos():
    grupos = cfg.ler_grupos({
        "casa_info": {"nome": "Casa e Info", "categorias": ["MLB1574", "mlb1648"]},
        "bebe": {"categorias": {"MLB1384": "Bebês"}},
        "vazio": {"nome": "Sem categorias"},
    })
    assert [g.chave for g in grupos] == ["casa_info", "bebe"]  # grupo sem categoria é ignorado
    assert grupos[0].categorias == {"MLB1574": "Casa, Móveis e Decoração", "MLB1648": "Informática"}
    assert grupos[1].nome == "bebe"


def test_repeticao_e_por_grupo(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_DB", tmp_path / "t.db")
    o = Oferta("mercadolivre", "MLB1", "x", "https://ml/1")
    db.registrar(o, "casa")
    assert db.ja_enviada(o.uid, 7, "casa")
    assert not db.ja_enviada(o.uid, 7, "bebe")  # outro grupo ainda pode receber


def test_config_padrao_tem_os_grupos():
    grupos = {g.chave: g for g in cfg.config.grupos}
    assert list(grupos) == ["mulher", "bebe"]
    assert grupos["mulher"].whatsapp == "Achadinhos da Mulher 💄"
    assert grupos["bebe"].categorias["MLB5366"] == "Roupas para Bebês"


def test_grupo_com_whatsapp():
    [g] = cfg.ler_grupos({"bebe": {"categorias": ["MLB1384"], "whatsapp": " Ofertas Bebê "}})
    assert g.whatsapp == "Ofertas Bebê"


def test_nao_repete_mesmo_produto_com_id_diferente(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_DB", tmp_path / "t.db")
    db.registrar(Oferta("mercadolivre", "MLB111", "Fone Bluetooth XYZ Pro Max Preto", "u"), "g")
    # mesmo produto vindo da página de ofertas, com outro id e outra cor
    assert db.ja_enviada("mercadolivre:MLB999", 7, "g", "Fone Bluetooth XYZ Pro Max Branco")
    assert not db.ja_enviada("mercadolivre:MLB999", 7, "g", "Mouse Gamer ABC")
    assert not db.ja_enviada("mercadolivre:MLB999", 7, "outro", "Fone Bluetooth XYZ Pro Max Branco")


def test_banco_antigo_ganha_coluna_chave(monkeypatch, tmp_path):
    import sqlite3
    arq = tmp_path / "velho.db"
    with sqlite3.connect(arq) as c:
        c.execute("CREATE TABLE envios (grupo TEXT, uid TEXT, plataforma TEXT, titulo TEXT,"
                  " preco REAL, enviada_em TEXT, PRIMARY KEY (grupo, uid))")
        c.execute("INSERT INTO envios VALUES ('g','mercadolivre:1','mercadolivre','x',1,'2026-01-01T00:00:00')")
    monkeypatch.setattr(db, "_DB", arq)
    db.registrar(Oferta("mercadolivre", "2", "Produto Novo", "u"), "g")
    assert db.total_enviadas() == 2
