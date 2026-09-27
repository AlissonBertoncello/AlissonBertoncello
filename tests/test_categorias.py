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
    assert [g.chave for g in cfg.config.grupos] == ["casa_info", "bebe"]


def test_grupo_com_whatsapp():
    [g] = cfg.ler_grupos({"bebe": {"categorias": ["MLB1384"], "whatsapp": " Ofertas Bebê "}})
    assert g.whatsapp == "Ofertas Bebê"
