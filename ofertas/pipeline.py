import logging
import time

from . import afiliado_ml, db
from .config import config, dentro_do_horario
from .destinos import Destino
from .formatter import montar_mensagem
from .models import Grupo, Oferta
from .sources import mercadolivre, shopee

log = logging.getLogger("ofertas.pipeline")


def coletar(categorias: dict[str, str] | None = None) -> list[Oferta]:
    """Busca ofertas nas fontes ativas (só nas categorias dadas, se houver)."""
    todas: list[Oferta] = []
    if config.fonte_ml.get("ativa"):
        try:
            todas += mercadolivre.buscar_ofertas(so_categorias=categorias)
        except Exception as e:
            log.error("Mercado Livre: %s", e)
    return todas


def filtrar(ofertas: list[Oferta], grupo: str) -> list[Oferta]:
    aprovadas = []
    for o in ofertas:
        if not o.titulo:
            continue
        if db.ja_enviada(o.uid, config.nao_repetir_dias, grupo, o.titulo):
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
    return db.chave_do_titulo(titulo)


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
    """Gera os links de afiliado (só das candidatas: o Linkbuilder é caro) e
    descarta as que ficaram sem link: oferta sem link de afiliado nunca é enviada.
    A Shopee já devolve o link de afiliado pronto; o Linkbuilder é só do Mercado Livre."""
    do_ml = [o for o in ofertas if o.plataforma == "mercadolivre"]
    if do_ml:
        try:
            afiliado_ml.gerar_links_afiliado(do_ml)
        except Exception as e:
            log.error("Linkbuilder ML falhou (link de afiliado não gerado): %s", e)
    for o in ofertas:
        if not o.url_afiliado:
            log.warning("Sem link de afiliado, descartada: %s", o.titulo[:60])
    return [o for o in ofertas if o.url_afiliado]


# rodízios (vivem enquanto o bot roda), por grupo:
_proxima: dict[str, int] = {}          # próxima categoria do Mercado Livre
_proxima_shopee: dict[str, int] = {}   # próxima palavra-chave da Shopee
_loja_da_vez: dict[str, int] = {}      # alterna as lojas a cada ciclo (meio a meio)
_avisou_shopee: set[str] = set()       # avisa só uma vez que a Shopee está fora
TENTATIVAS_SHOPEE = 3                  # palavras tentadas por ciclo antes de desistir


def _candidatas_ml(grupo: Grupo, n: int) -> list[Oferta]:
    """Começa na categoria do rodízio; se ela não tiver oferta nova, tenta a seguinte."""
    cats = list(grupo.categorias.items())
    if not cats or not config.fonte_ml.get("ativa"):
        return []
    inicio = _proxima.get(grupo.chave, 0) % len(cats)
    for passo in range(len(cats)):
        idx = (inicio + passo) % len(cats)
        cid, nome = cats[idx]
        brutas = coletar({cid: nome})
        boas = filtrar(brutas, grupo.chave)
        log.info("[%s] %s: %d coletadas, %d novas nos filtros", grupo.nome, nome, len(brutas), len(boas))
        # reservas: se uma ficar sem link de afiliado, a próxima melhor entra no lugar
        candidatas = escolher(boas, n * 3)
        if candidatas:
            _proxima[grupo.chave] = idx + 1
            return candidatas
    _proxima[grupo.chave] = inicio + 1
    return []


def _shopee_disponivel(grupo: Grupo) -> bool:
    if not (grupo.shopee and config.fonte_shopee.get("ativa")):
        return False
    if not shopee.tem_credenciais():
        if "credenciais" not in _avisou_shopee:
            _avisou_shopee.add("credenciais")
            log.warning("Shopee: sem SHOPEE_APP_ID/SHOPEE_APP_SECRET no .env — usando só o "
                        "Mercado Livre por enquanto")
        return False
    return True


def _candidatas_shopee(grupo: Grupo, n: int) -> list[Oferta]:
    """Palavra-chave da vez na Shopee; se não render oferta nova, tenta mais algumas."""
    if not _shopee_disponivel(grupo):
        return []
    termos = grupo.shopee
    inicio = _proxima_shopee.get(grupo.chave, 0) % len(termos)
    for passo in range(min(TENTATIVAS_SHOPEE, len(termos))):
        idx = (inicio + passo) % len(termos)
        try:
            brutas = shopee.buscar(termos[idx])
        except Exception as e:
            log.error("[%s] Shopee '%s': %s", grupo.nome, termos[idx], e)
            _proxima_shopee[grupo.chave] = idx + 1
            return []
        boas = filtrar(brutas, grupo.chave)
        log.info("[%s] Shopee '%s': %d coletadas, %d novas nos filtros",
                 grupo.nome, termos[idx], len(brutas), len(boas))
        candidatas = escolher(boas, n * 3)
        if candidatas:
            _proxima_shopee[grupo.chave] = idx + 1
            return candidatas
    _proxima_shopee[grupo.chave] = inicio + min(TENTATIVAS_SHOPEE, len(termos))
    return []


def candidatas_do_grupo(grupo: Grupo, n: int) -> list[Oferta]:
    """Candidatas da vez: alterna as lojas a cada ciclo (Mercado Livre / Shopee);
    se a loja da vez não tiver oferta nova (ou estiver indisponível), usa a outra."""
    lojas = [_candidatas_ml, _candidatas_shopee]
    vez = _loja_da_vez.get(grupo.chave, 0) % len(lojas)
    _loja_da_vez[grupo.chave] = vez + 1
    for buscar in (lojas[vez], lojas[1 - vez]):
        candidatas = buscar(grupo, n)
        if candidatas:
            return candidatas
    log.info("[%s] nenhuma oferta nova nas categorias do grupo", grupo.nome)
    return []


def executar_ciclo(destino: Destino, grupos: list[Grupo], registrar: bool = True) -> int:
    """Para cada grupo: coletar -> filtrar -> escolher; depois gera os links de
    afiliado de todos de uma vez e envia. Retorna o nº de ofertas enviadas."""
    if not dentro_do_horario():
        log.info("Fora do horário ativo (%s) — ciclo pulado", config.horario_ativo)
        return 0

    n = config.max_posts_por_ciclo
    # um Chrome só no ciclo inteiro (páginas de ofertas + Linkbuilder), aberto só se precisar
    with afiliado_ml.chrome_compartilhado():
        por_grupo = {g.chave: candidatas_do_grupo(g, n) for g in grupos}
        todas = [o for lista in por_grupo.values() for o in lista]
        if todas:
            # link de afiliado é obrigatório: um único lote no Linkbuilder para todos os grupos
            com_link_afiliado(todas)

    enviadas = 0
    ultimo_envio = 0.0
    for g in grupos:
        candidatas = por_grupo[g.chave]
        escolhidas = [o for o in candidatas if o.url_afiliado][:n]
        if candidatas and not escolhidas:
            log.error("[%s] nenhuma oferta enviada: não foi possível gerar link de afiliado "
                      "(motivo na linha 'Linkbuilder ML falhou' acima)", g.nome)
        for o in escolhidas:
            # pausa entre envios (inclusive de grupos diferentes): ritmo mais humano no WhatsApp
            if enviadas and destino.nome != "console":
                time.sleep(max(0.0, config.espacamento_segundos - (time.monotonic() - ultimo_envio)))
            try:
                destino.enviar(o, montar_mensagem(o, g), g)
            except Exception as e:
                log.error("[%s] falha ao enviar '%s': %s", g.nome, o.titulo[:60], e)
                continue
            ultimo_envio = time.monotonic()
            if registrar:
                db.registrar(o, g.chave)
            enviadas += 1

    log.info("Ciclo: %d oferta(s) enviada(s) para %d grupo(s) (%s)", enviadas, len(grupos), destino.nome)
    return enviadas
