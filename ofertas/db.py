import datetime as dt
import re
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
    c.execute(
        "CREATE TABLE IF NOT EXISTS cupons ("
        " grupo TEXT,"
        " ident TEXT,"
        " dia TEXT,"
        " horario TEXT,"
        " enviada_em TEXT)"
    )
    colunas = {r[1] for r in c.execute("PRAGMA table_info(envios)")}
    if "chave" not in colunas:  # bancos criados antes desta versão
        c.execute("ALTER TABLE envios ADD COLUMN chave TEXT")
    return c


def chave_do_titulo(titulo: str) -> str:
    """Primeiras palavras do nome: o mesmo produto (ou variação de cor/tamanho) vindo
    de fontes diferentes, com ids diferentes, tem a mesma chave."""
    return " ".join(re.findall(r"\w+", titulo.lower())[:5])


def ja_enviada(uid: str, dentro_de_dias: int, grupo: str, titulo: str = "") -> bool:
    """True se o produto (mesmo id ou mesmo nome) já foi enviado PARA ESSE GRUPO no prazo."""
    limite = (dt.datetime.now() - dt.timedelta(days=dentro_de_dias)).isoformat(timespec="seconds")
    chave = chave_do_titulo(titulo) if titulo else None
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM envios WHERE grupo = ? AND enviada_em > ? AND (uid = ? OR chave = ?)",
            (grupo, limite, uid, chave)).fetchone()
    return row is not None


def registrar(oferta: Oferta, grupo: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO envios (grupo, uid, plataforma, titulo, preco, enviada_em, chave)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (grupo, oferta.uid, oferta.plataforma, oferta.titulo, oferta.preco,
             dt.datetime.now().isoformat(timespec="seconds"), chave_do_titulo(oferta.titulo)),
        )


def total_enviadas() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM envios").fetchone()[0]


def ultimos_titulos(grupo: str, n: int) -> list[str]:
    """Títulos das últimas n ofertas enviadas ao grupo (a mais recente primeiro)."""
    with _conn() as c:
        return [r[0] or "" for r in c.execute(
            "SELECT titulo FROM envios WHERE grupo = ? ORDER BY enviada_em DESC LIMIT ?", (grupo, n))]


def titulos_desde(grupo: str, dias: int) -> list[str]:
    """Títulos enviados ao grupo nos últimos `dias` dias."""
    limite = (dt.datetime.now() - dt.timedelta(days=dias)).isoformat(timespec="seconds")
    with _conn() as c:
        return [r[0] or "" for r in c.execute(
            "SELECT titulo FROM envios WHERE grupo = ? AND enviada_em > ?", (grupo, limite))]


# ── cupons ───────────────────────────────────────────────────────────

def horarios_de_cupom_feitos(grupo: str, dia: str) -> set[str]:
    """Horários de cupom já cumpridos hoje no grupo (postados ou pulados)."""
    with _conn() as c:
        return {r[0] for r in c.execute(
            "SELECT horario FROM cupons WHERE grupo = ? AND dia = ?", (grupo, dia))}


def registrar_cupom(grupo: str, ident: str, dia: str, horarios: list[str],
                    em: dt.datetime | None = None) -> None:
    agora = (em or dt.datetime.now()).isoformat(timespec="seconds")
    with _conn() as c:
        c.executemany("INSERT INTO cupons (grupo, ident, dia, horario, enviada_em) VALUES (?, ?, ?, ?, ?)",
                      [(grupo, ident, dia, h, agora) for h in horarios])


def ultimo_envio_cupom(grupo: str, ident: str) -> str:
    """Quando o cupom foi postado no grupo pela última vez ("" = nunca)."""
    with _conn() as c:
        row = c.execute("SELECT MAX(enviada_em) FROM cupons WHERE grupo = ? AND ident = ?",
                        (grupo, ident)).fetchone()
    return (row[0] or "") if row else ""
