import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Navegador do Playwright fica dentro do projeto (fallback quando não há Google Chrome).
# Instale com: uv run python -m ofertas instalar-navegador
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(DATA_DIR / "pw-browsers"))

load_dotenv(BASE_DIR / ".env")

from .categorias import nome as nome_categoria  # noqa: E402
from .models import Grupo  # noqa: E402


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
        self.ml_etiqueta: str = os.getenv("ML_ETIQUETA", "").strip()
        self.shopee_app_id: str = os.getenv("SHOPEE_APP_ID", "").strip()
        self.shopee_app_secret: str = os.getenv("SHOPEE_APP_SECRET", "").strip()
        self.evolution_url: str = os.getenv("EVOLUTION_URL", "http://localhost:8080").strip()
        self.evolution_api_key: str = os.getenv("EVOLUTION_API_KEY", "").strip()
        self.evolution_instancia: str = os.getenv("EVOLUTION_INSTANCIA", "bot-ofertas").strip()

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
        self.fonte_shopee: dict = fontes.get("shopee") or {"ativa": False}

        self.destino: str = str(y.get("destino") or "console").strip().lower()
        self.grupos: list[Grupo] = ler_grupos(y.get("grupos") or {})


def _convite(valor) -> str:
    """Link de convite do grupo; vazio enquanto for só o lembrete entre colchetes
    (ex: "[LINK DE CONVITE ...]") ou qualquer coisa que não seja um link."""
    texto = str(valor or "").strip() if isinstance(valor, str) else ""
    return texto if texto.startswith(("https://", "http://")) else ""


def ler_grupos(dados: dict) -> list[Grupo]:
    """grupos do config.yaml -> [Grupo]. categorias: lista de ids ou {id: nome}."""
    grupos = []
    for chave, g in dados.items():
        g = g or {}
        cats = g.get("categorias") or []
        if isinstance(cats, dict):
            cats = {str(k): str(v) for k, v in cats.items()}
        else:
            cats = {str(c).strip().upper(): nome_categoria(str(c).strip().upper()) for c in cats}
        shopee = [str(t).strip() for t in (g.get("shopee") or []) if str(t).strip()]
        if cats or shopee:
            grupos.append(Grupo(chave=str(chave), nome=str(g.get("nome") or chave), categorias=cats,
                                whatsapp=str(g.get("whatsapp") or "").strip(),
                                convite=_convite(g.get("convite")), shopee=shopee))
    return grupos


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
    if not config.ml_etiqueta:
        pendencias.append("ML_ETIQUETA (a 'Etiqueta em uso' do Linkbuilder do ML)")
    perfil_ml = DATA_DIR / "ml_profile"
    if not (perfil_ml.exists() and any(perfil_ml.iterdir())):
        pendencias.append("Sessão do Mercado Livre (rode: uv run python -m ofertas ml-login)")
    if config.destino == "whatsapp":
        sem = [g.chave for g in config.grupos if not g.whatsapp]
        if sem:
            pendencias.append(f"'whatsapp:' (nome do grupo) nos grupos: {', '.join(sem)}")
    if config.fonte_shopee.get("ativa") and any(g.shopee for g in config.grupos) \
            and not (config.shopee_app_id and config.shopee_app_secret):
        pendencias.append("SHOPEE_APP_ID / SHOPEE_APP_SECRET (opcional: sem eles o bot usa só o "
                          "Mercado Livre — painel de afiliados da Shopee > Open API)")
    if not config.grupos:
        pendencias.append("grupos no config.yaml (pelo menos um grupo com categorias)")
    return pendencias
