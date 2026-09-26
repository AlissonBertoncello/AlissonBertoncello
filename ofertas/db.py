import datetime as dt
import sqlite3

from .config import DATA_DIR
from .models import Oferta

_DB = DATA_DIR / "ofertas.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS enviadas ("
        " uid TEXT PRIMARY KEY,"
        " plataforma TEXT,"
        " titulo TEXT,"
        " preco REAL,"
        " enviada_em TEXT)"
    )
    return c


def ja_enviada(uid: str, dentro_de_dias: int) -> bool:
    with _conn() as c:
        row = c.execute("SELECT enviada_em FROM enviadas WHERE uid = ?", (uid,)).fetchone()
    if not row:
        return False
    enviada = dt.datetime.fromisoformat(row[0])
    return (dt.datetime.now() - enviada) < dt.timedelta(days=dentro_de_dias)


def registrar(oferta: Oferta) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO enviadas (uid, plataforma, titulo, preco, enviada_em)"
            " VALUES (?, ?, ?, ?, ?)",
            (oferta.uid, oferta.plataforma, oferta.titulo, oferta.preco,
             dt.datetime.now().isoformat(timespec="seconds")),
        )


def total_enviadas() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM enviadas").fetchone()[0]
