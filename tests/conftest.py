import pytest

from ofertas import db, pipeline
from ofertas.sources import ml_geral, ml_pagina, shopee


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    """Testes nunca usam o banco de verdade nem dependem da internet."""
    monkeypatch.setattr(db, "_DB", tmp_path / "ofertas.db")
    monkeypatch.setattr(pipeline, "rede_ok", lambda: True)
    monkeypatch.setattr(pipeline, "_shopee_falhou", set())
    monkeypatch.setattr(pipeline, "_pagina_lista_shopee", {})
    monkeypatch.setattr(pipeline, "_lista_shopee_recusada", set())
    monkeypatch.setattr(ml_pagina, "_pausada_ate", 0.0)
    for nome in ("_estoque", "_lida_em", "_pagina_da_vez", "_termos", "_rodizio_dep", "_rodizio_termo"):
        monkeypatch.setattr(ml_geral, nome, {})
    monkeypatch.setattr(ml_geral, "_pausada_ate", 0.0)
    monkeypatch.setattr(ml_geral, "ARQ_TERMOS", tmp_path / "termos.json")

    def sem_link_por_grupo(*a, **k):  # nunca chama a Shopee de verdade nos testes
        raise shopee.ErroShopee("teste")
    monkeypatch.setattr(shopee, "link_afiliado", sem_link_por_grupo)
    monkeypatch.setattr(ml_geral, "_chrome_ler", lambda urls: {})  # nunca abre um Chrome de verdade
