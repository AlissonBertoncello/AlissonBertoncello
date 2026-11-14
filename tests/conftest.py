import pytest

from ofertas import db, pipeline
from ofertas.sources import ml_pagina


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    """Testes nunca usam o banco de verdade nem dependem da internet."""
    monkeypatch.setattr(db, "_DB", tmp_path / "ofertas.db")
    monkeypatch.setattr(pipeline, "rede_ok", lambda: True)
    monkeypatch.setattr(pipeline, "_shopee_falhou", set())
    monkeypatch.setattr(ml_pagina, "_pausada_ate", 0.0)
