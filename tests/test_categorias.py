from ofertas import categorias
from ofertas.sources import mercadolivre


def test_resolver():
    assert categorias.resolver("1") == ("MLB1648", "Informática")
    assert categorias.resolver("mlb1051") == ("MLB1051", "Celulares e Telefones")
    assert categorias.resolver("games") == ("MLB1144", "Games")
    assert categorias.resolver("999") is None
    assert categorias.resolver("") is None


def test_perguntar_repete_ate_valido(monkeypatch, capsys):
    respostas = iter(["abc", "3"])
    monkeypatch.setattr("builtins.input", lambda _: next(respostas))
    assert categorias.perguntar() == ("MLB1051", "Celulares e Telefones")
    assert "Opção inválida" in capsys.readouterr().out


def test_so_a_categoria_escolhida(monkeypatch):
    monkeypatch.setattr(mercadolivre.config, "fonte_ml",
                        {"buscas": ["air fryer"], "categorias": {"MLB1648": "Info"}})
    assert mercadolivre._consultas({"MLB1144": "Games"}) == [("categoria Games", {"categoria": "MLB1144"})]
    assert len(mercadolivre._consultas()) == 2
