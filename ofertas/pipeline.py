import logging
import re
import time

from . import afiliado_ml, db
from .config import config, dentro_do_horario
from .destinos import Destino
from .formatter import montar_mensagem
from .models import Oferta
from .sources import mercadolivre

log = logging.getLogger("ofertas.pipeline")


def coletar() -> list[Oferta]:
    """Busca ofertas nas fontes ativas."""
    todas: list[Oferta] = []
    if config.fonte_ml.get("ativa"):
        try:
            todas += mercadolivre.buscar_ofertas()
        except Exception as e:
            log.error("Mercado Livre: %s", e)
    return todas


def filtrar(ofertas: list[Oferta]) -> list[Oferta]:
    aprovadas = []
    for o in ofertas:
        if not o.titulo:
            continue
        if db.ja_enviada(o.uid, config.nao_repetir_dias):
            continue
        if config.desconto_minimo and (o.desconto or 0) < config.desconto_minimo:
            continue
        if o.preco is not None:
            if config.preco_minimo and o.preco < config.preco_minimo:
                continue
            if config.preco_maximo and o.preco > config.preco_maximo:
                continue
        titulo = o.titulo.lower()
        if any(p in titulo for p in config.palavras_bloqueadas):
            continue
        aprovadas.append(o)
    return aprovadas


def _chave_similar(titulo: str) -> str:
    """Variações do mesmo produto (cor, tamanho) costumam repetir as primeiras palavras."""
    return " ".join(re.findall(r"\w+", titulo.lower())[:5])


def escolher(ofertas: list[Oferta], n: int) -> list[Oferta]:
    """Top N por desconto, pulando variações do mesmo produto."""
    escolhidas: list[Oferta] = []
    vistas: set[str] = set()
    for o in sorted(ofertas, key=lambda o: o.desconto or 0, reverse=True):
        chave = _chave_similar(o.titulo)
        if chave in vistas:
            continue
        vistas.add(chave)
        escolhidas.append(o)
        if len(escolhidas) >= n:
            break
    return escolhidas


def com_link_afiliado(ofertas: list[Oferta]) -> list[Oferta]:
    """Gera os links de afiliado (só das escolhidas: o Linkbuilder é caro) e
    descarta as que ficaram sem link, para nunca enviar oferta sem comissão."""
    try:
        afiliado_ml.gerar_links_afiliado(ofertas)
    except Exception as e:
        log.error("Linkbuilder ML falhou: %s", e)
    prontas = [o for o in ofertas if o.url_afiliado]
    for o in ofertas:
        if not o.url_afiliado:
            log.warning("Sem link de afiliado, pulando: %s", o.titulo[:60])
    return prontas


def executar_ciclo(destino: Destino, registrar: bool = True) -> int:
    """coletar -> filtrar -> escolher -> enviar. Retorna nº de ofertas enviadas."""
    if not dentro_do_horario():
        log.info("Fora do horário ativo (%s) — ciclo pulado", config.horario_ativo)
        return 0

    brutas = coletar()
    boas = filtrar(brutas)
    escolhidas = escolher(boas, config.max_posts_por_ciclo)
    if config.ml_afiliado:
        escolhidas = com_link_afiliado(escolhidas)

    enviadas = 0
    for o in escolhidas:
        try:
            destino.enviar(o, montar_mensagem(o))
        except Exception as e:
            log.error("Falha ao enviar '%s': %s", o.titulo[:60], e)
            continue
        if registrar:
            db.registrar(o)
        enviadas += 1
        if o is not escolhidas[-1] and destino.nome != "console":
            time.sleep(config.espacamento_segundos)

    log.info("Ciclo: %d coletadas, %d aprovadas, %d enviadas (%s)",
             len(brutas), len(boas), enviadas, destino.nome)
    return enviadas
