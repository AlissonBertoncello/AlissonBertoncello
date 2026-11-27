from ofertas import busca_ml
from ofertas.sources import ml_pagina
from ofertas.sources.mercadolivre import ErroAPI

CARD = """<div class="poly-card"><a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-1234567890-tenis-_JM">Tênis Nike</a>
<div class="poly-price__current"><span class="andes-money-amount__fraction">199</span></div></div>"""


class Cliente:
    def token(self):
        return "t"

    def get(self, caminho, params=None):
        if caminho.startswith("/highlights"):
            return {"content": [{"id": "MLB1", "type": "ITEM"}, {"id": "MLB2", "type": "PRODUCT"},
                                {"id": "MLBU3", "type": "USER_PRODUCT"}]}
        if caminho == "/items":
            return [{"code": 200, "body": {"title": "Fone JBL", "price": 99.0, "original_price": 199.0,
                                           "permalink": "https://ml/1"}}]
        if caminho == "/products/MLB2":
            return {"name": "Relógio Casio", "buy_box_winner": None}
        if caminho == "/products/MLB2/items":
            raise ErroAPI("GET /products/MLB2/items respondeu HTTP 403: forbidden")
        if caminho.startswith("/user-products"):
            raise ErroAPI("HTTP 404")
        if caminho == "/products/search":
            return {"results": [{"id": "MLB9", "name": "Tênis Nike Air"}]}
        if caminho == "/products/MLB9/items":
            return {"results": [{"price": 299.0, "original_price": 499.0}]}
        raise ErroAPI("HTTP 404")


def test_busca_crua_mostra_cada_caminho(monkeypatch, tmp_path):
    monkeypatch.setattr(busca_ml, "PASTA", tmp_path)
    monkeypatch.setattr(busca_ml, "CATEGORIAS", {"MLB1430": "Moda"})
    monkeypatch.setattr(busca_ml, "PALAVRAS", ["tênis nike"])
    monkeypatch.setattr(busca_ml.ClienteML, "do_config", classmethod(lambda cls: Cliente()))
    monkeypatch.setattr(ml_pagina, "_html_navegador",
                        lambda urls: {u: f"<html><head><title>Ofertas</title></head><body>{CARD}</body></html>" for u in urls})
    busca_ml.rodar()
    texto = (tmp_path / "resultado.txt").read_text(encoding="utf-8")
    assert "página de ofertas: 3" in texto  # 3 páginas, 1 produto cada
    assert "Fone JBL — R$ 99.00 (de R$ 199.00)" in texto
    assert "Relógio Casio — SEM PREÇO" in texto and "HTTP 403" in texto  # mostra onde o preço some
    assert "USER_PRODUCT MLBU3: ❌ HTTP 404" in texto
    assert "Tênis Nike Air — R$ 299.00" in texto
    assert (tmp_path / "api_ranking_MLB1430.json").exists() and (tmp_path / "pagina_1.html").exists()
