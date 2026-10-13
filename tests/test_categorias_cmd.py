import argparse

from ofertas import main
from ofertas.sources import mercadolivre


class ClienteFalso:
    def categoria(self, cid):
        if cid == "MLB1276":
            return {"id": "MLB1276", "name": "Esportes e Fitness",
                    "path_from_root": [{"name": "Esportes e Fitness"}],
                    "children_categories": [
                        {"id": "MLB2", "name": "Pesca", "total_items_in_this_category": 500},
                        {"id": "MLB1", "name": "Fitness e Musculação", "total_items_in_this_category": 12300}]}
        return {"id": cid, "name": "x", "children_categories": [{"id": cid + "9", "name": "Neta"}]}

    def categorias_raiz(self):
        return [{"id": "MLB1276", "name": "Esportes e Fitness"}, {"id": "MLB1384", "name": "Bebês"}]


def test_lista_subcategorias_no_formato_do_config(monkeypatch, capsys):
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: ClienteFalso())
    main.cmd_categorias(argparse.Namespace(id="mlb1276", niveis=1))
    saida = capsys.readouterr().out
    assert "  MLB1: Fitness e Musculação  (12.300 anúncios)" in saida
    assert saida.index("MLB1:") < saida.index("MLB2:")  # mais anúncios primeiro


def test_dois_niveis_e_principais(monkeypatch, capsys):
    monkeypatch.setattr(mercadolivre, "cliente_padrao", lambda: ClienteFalso())
    main.cmd_categorias(argparse.Namespace(id="MLB1276", niveis=2))
    assert "      MLB19: Neta" in capsys.readouterr().out
    main.cmd_categorias(argparse.Namespace(id=None, niveis=1))
    assert "  MLB1384: Bebês" in capsys.readouterr().out
