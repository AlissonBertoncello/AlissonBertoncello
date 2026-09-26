import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")


def _ler_yaml() -> dict:
    caminho = BASE_DIR / "config.yaml"
    if not caminho.exists():
        return {}
    with open(caminho, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Config:
    def __init__(self):
        y = _ler_yaml()
        geral = y.get("geral") or {}
        filtros = y.get("filtros") or {}

        # .env (segredos)
        self.ml_client_id: str = os.getenv("ML_CLIENT_ID", "").strip()
        self.ml_client_secret: str = os.getenv("ML_CLIENT_SECRET", "").strip()
        self.ml_access_token: str = os.getenv("ML_ACCESS_TOKEN", "").strip()

        # config.yaml
        self.intervalo_minutos: int = int(geral.get("intervalo_minutos", 45))
        self.max_posts_por_ciclo: int = int(geral.get("max_posts_por_ciclo", 3))
        self.espacamento_segundos: int = int(geral.get("espacamento_segundos", 60))
        self.nao_repetir_dias: int = int(geral.get("nao_repetir_dias", 7))
        self.horario_ativo: str = str(geral.get("horario_ativo") or "").strip()  # "08:00-23:00"; vazio = 24h

        self.desconto_minimo: int = int(filtros.get("desconto_minimo", 0))
        self.preco_minimo: float = float(filtros.get("preco_minimo", 0))
        self.preco_maximo: float = float(filtros.get("preco_maximo", 0))
        self.palavras_bloqueadas: list[str] = [
            str(p).lower() for p in (filtros.get("palavras_bloqueadas") or [])
        ]

        fontes = y.get("fontes") or {}
        self.fonte_ml: dict = fontes.get("mercadolivre") or {"ativa": False}

        self.destino: str = str(y.get("destino") or "console").strip().lower()


config = Config()


def dentro_do_horario(agora: datetime | None = None) -> bool:
    """True se agora está dentro de geral.horario_ativo (aceita janela virando a noite)."""
    if not config.horario_ativo:
        return True
    try:
        inicio, fim = config.horario_ativo.split("-")
        h1, m1 = (int(x) for x in inicio.strip().split(":"))
        h2, m2 = (int(x) for x in fim.strip().split(":"))
    except ValueError:
        return True  # formato inválido: não bloqueia
    agora = agora or datetime.now()
    t, a, b = agora.hour * 60 + agora.minute, h1 * 60 + m1, h2 * 60 + m2
    return a <= t < b if a <= b else (t >= a or t < b)


def verificar() -> list[str]:
    """Retorna a lista do que ainda falta configurar."""
    pendencias = []
    if not (config.ml_access_token or (config.ml_client_id and config.ml_client_secret)):
        pendencias.append("ML_CLIENT_ID / ML_CLIENT_SECRET (app em developers.mercadolivre.com.br)")
    return pendencias
