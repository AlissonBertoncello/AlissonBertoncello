"""Posts de cupom nos horários do config (aba Cupons do painel).

Em cada horário (ex.: 10:00, 15:00, 20:00), cada grupo recebe um post de cupom:
primeiro os cupons cadastrados no painel (em rodízio, até vencerem); se não houver
nenhum válido, uma campanha da Shopee (quando ligada). O link sempre é de afiliado:
cupom cujo link não vira link de afiliado não é postado.
"""
import datetime as dt
import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import afiliado_ml, db
from .config import config
from .formatter import montar_mensagem_cupom
from .models import Cupom, Grupo, Oferta
from .sources import shopee

log = logging.getLogger("ofertas.cupons")

REPETIR_CAMPANHA_DIAS = 2  # a mesma campanha da Shopee não volta ao grupo antes disso
_HOSTS_CURTOS_SHOPEE = ("s.shopee.com.br", "shope.ee")


@dataclass
class PostCupom:
    grupo: Grupo
    oferta: Oferta
    mensagem: str
    ident: str
    horarios: list[str] = field(default_factory=list)  # horários de hoje que este post cumpre


def loja_do_link(link: str) -> str | None:
    host = (urlparse(link).hostname or "").lower()
    if afiliado_ml.e_link_ml(link):
        return "mercadolivre"
    if "shopee" in host or host == "shope.ee":
        return "shopee"
    return None


def link_afiliado(cupom: Cupom, loja: str) -> str:
    """Link do cupom como link de afiliado (o meli.la/s.shopee colado no painel já é)."""
    host = (urlparse(cupom.link).hostname or "").lower()
    if loja == "mercadolivre":
        if host == "meli.la":
            return cupom.link
        o = Oferta("mercadolivre", cupom.ident, cupom.descricao, cupom.link)
        afiliado_ml.gerar_links_afiliado([o])
        return o.url_afiliado
    if host in _HOSTS_CURTOS_SHOPEE:
        return cupom.link
    return shopee.link_afiliado(cupom.link)


def horarios_pendentes(grupo: Grupo, agora: dt.datetime) -> list[str]:
    """Horários de cupom de hoje que já passaram e ainda não foram cumpridos no grupo."""
    hora = agora.strftime("%H:%M")
    feitos = db.horarios_de_cupom_feitos(grupo.chave, agora.date().isoformat())
    return [h for h in config.cupons.horarios if h <= hora and h not in feitos]


def _validade_br(texto: str) -> str:
    try:
        return dt.date.fromisoformat(texto).strftime("%d/%m")
    except ValueError:
        return ""


def _do_painel(grupo: Grupo, hoje: dt.date) -> PostCupom | None:
    """Cupom válido do painel que está há mais tempo sem sair no grupo."""
    validos = [c for c in config.cupons.lista if c.para(grupo.chave) and c.vale_em(hoje)]
    validos.sort(key=lambda c: db.ultimo_envio_cupom(grupo.chave, c.ident))
    for c in validos:
        loja = loja_do_link(c.link)
        if loja is None:
            log.warning("Cupom '%s': o link precisa ser do Mercado Livre ou da Shopee", c.descricao[:50])
            continue
        try:
            link = link_afiliado(c, loja)
        except Exception as e:
            link = ""
            log.warning("Cupom '%s': link de afiliado não gerado (%s)", c.descricao[:50], e)
        if not link:
            log.warning("Cupom '%s' não postado: sem link de afiliado. Gere o link no painel de "
                        "afiliados da loja (meli.la / s.shopee.com.br) e cole no painel.", c.descricao[:50])
            continue
        o = Oferta(loja, c.ident, c.descricao, c.link, url_afiliado=link)
        msg = montar_mensagem_cupom(o, grupo, codigo=c.codigo, validade=_validade_br(c.validade))
        return PostCupom(grupo, o, msg, c.ident)
    return None


def _campanha_shopee(grupo: Grupo, agora: dt.datetime) -> PostCupom | None:
    cc = config.cupons
    if not (cc.shopee_campanhas and config.fonte_shopee.get("ativa") and shopee.tem_credenciais()):
        return None
    if cc.grupos_campanhas and grupo.chave not in cc.grupos_campanhas:
        return None
    try:
        achadas = shopee.campanhas()
    except Exception as e:
        log.warning("[%s] campanhas da Shopee: %s", grupo.nome, e)
        return None
    limite = (agora - dt.timedelta(days=REPETIR_CAMPANHA_DIAS)).isoformat(timespec="seconds")
    for c in achadas:
        ident = "campanha:" + c["nome"][:80]
        if db.ultimo_envio_cupom(grupo.chave, ident) > limite:
            continue
        o = Oferta("shopee", ident, c["nome"], c["link"], imagem=c["imagem"], url_afiliado=c["link"])
        validade = ""
        if c["fim"]:
            validade = dt.datetime.fromtimestamp(c["fim"]).strftime("%d/%m às %Hh%M")
        msg = montar_mensagem_cupom(o, grupo, validade=validade, campanha=True)
        return PostCupom(grupo, o, msg, ident)
    return None


def da_vez(grupos: list[Grupo], agora: dt.datetime | None = None,
           registrar: bool = True) -> list[PostCupom]:
    """Posts de cupom que devem sair agora (um por grupo, no máximo)."""
    if not config.cupons.ligado:
        return []
    agora = agora or dt.datetime.now()
    posts = []
    for g in grupos:
        pendentes = horarios_pendentes(g, agora)
        if not pendentes:
            continue
        post = _do_painel(g, agora.date()) or _campanha_shopee(g, agora)
        if post:
            post.horarios = pendentes
            posts.append(post)
        else:
            log.info("[%s] horário de cupom (%s): nenhum cupom válido agora — pulado",
                     g.nome, pendentes[-1])
            if registrar:  # não tenta de novo a cada ciclo
                db.registrar_cupom(g.chave, "", agora.date().isoformat(), pendentes, agora)
    return posts


def registrar(post: PostCupom, agora: dt.datetime | None = None) -> None:
    agora = agora or dt.datetime.now()
    db.registrar_cupom(post.grupo.chave, post.ident, agora.date().isoformat(), post.horarios, agora)
