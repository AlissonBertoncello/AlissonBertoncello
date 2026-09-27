import datetime as dt
import sqlite3

from .config import DATA_DIR
from .models import Oferta

_DB = DATA_DIR / "ofertas.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS envios ("
        " grupo TEXT,"
        " uid TEXT,"
        " plataforma TEXT,"
        " titulo TEXT,"
        " preco REAL,"
        " enviada_em TEXT,"
        " PRIMARY KEY (grupo, uid))"
    )
    return c


def ja_enviada(uid: str, dentro_de_dias: int, grupo: str) -> bool:
    """True se o produto já foi enviado PARA ESSE GRUPO dentro do prazo."""
    with _conn() as c:
        row = c.execute("SELECT enviada_em FROM envios WHERE grupo = ? AND uid = ?",
                        (grupo, uid)).fetchone()
    if not row:
        return False
    enviada = dt.datetime.fromisoformat(row[0])
    return (dt.datetime.now() - enviada) < dt.timedelta(days=dentro_de_dias)


def registrar(oferta: Oferta, grupo: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO envios (grupo, uid, plataforma, titulo, preco, enviada_em)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (grupo, oferta.uid, oferta.plataforma, oferta.titulo, oferta.preco,
             dt.datetime.now().isoformat(timespec="seconds")),
        )


def total_enviadas() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM envios").fetchone()[0]
