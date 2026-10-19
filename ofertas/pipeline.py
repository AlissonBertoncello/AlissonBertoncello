import logging
import re
import time
from collections import Counter

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


def tem_palavra_bloqueada(titulo: str, extras: list[str] = ()) -> bool:
    """Lista geral + `extras` (as do grupo). Compara palavras inteiras:
    "pet" bloqueia "Cama Pet", mas não "Tapete"."""
    titulo = titulo.lower()
    return any(re.search(rf"(?<!\w){re.escape(p.lower())}(?!\w)", titulo)
               for p in [*config.palavras_bloqueadas, *extras] if p)


def motivo_descarte(o: Oferta, grupo: str, bloquear: list[str] = ()) -> str | None:
    """Por que a oferta não serve para o grupo (None = serve)."""
    if not o.titulo:
        return "sem título"
    if db.ja_enviada(o.uid, config.nao_repetir_dias, grupo, o.titulo):
        return "já enviadas"
    if config.desconto_minimo and (o.desconto or 0) < config.desconto_minimo:
        return f"desconto < {config.desconto_minimo}%"
    if o.preco is not None:
        if config.preco_minimo and o.preco < config.preco_minimo:
            return "preço baixo"
        if config.preco_maximo and o.preco > config.preco_maximo:
            return "preço alto"
    if tem_palavra_bloqueada(o.titulo, bloquear):
        return "palavra bloqueada"
    return None


def filtrar(ofertas: list[Oferta], grupo: str, bloquear: list[str] = (),
            motivos: Counter | None = None) -> list[Oferta]:
    """Ofertas que passam nos filtros; em `motivos` conta por que as outras saíram."""
    aprovadas = []
    for o in ofertas:
        motivo = motivo_descarte(o, grupo, bloquear)
        if motivo is None:
            aprovadas.append(o)
        elif motivos is not None:
            motivos[motivo] += 1
    return aprovadas


def _resumo(brutas: list, boas: list, motivos: Counter) -> str:
    """'65 coletadas, 33 novas nos filtros (fora: 20 já enviadas, 12 desconto < 10%)'."""
    texto = f"{len(brutas)} coletadas, {len(boas)} novas nos filtros"
    if motivos:
        texto += " (fora: " + ", ".join(f"{n} {m}" for m, n in motivos.most_common()) + ")"
    return texto


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
_loja_da_vez: dict[str, int] = {}      # posição na sequência de lojas (proporção do grupo)
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
        motivos = Counter()
        boas = filtrar(brutas, grupo.chave, grupo.bloquear, motivos)
        log.info("[%s] %s: %s", grupo.nome, nome, _resumo(brutas, boas, motivos))
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
        motivos = Counter()
        boas = filtrar(brutas, grupo.chave, grupo.bloquear, motivos)
        log.info("[%s] Shopee '%s': %s", grupo.nome, termos[idx], _resumo(brutas, boas, motivos))
        candidatas = escolher(boas, n * 3)
        if candidatas:
            _proxima_shopee[grupo.chave] = idx + 1
            return candidatas
    _proxima_shopee[grupo.chave] = inicio + min(TENTATIVAS_SHOPEE, len(termos))
    return []


def sequencia_lojas(grupo: Grupo) -> list[str]:
    """Ordem das lojas nos ciclos do grupo, intercalada pela proporção.
    Ex.: 3 ML : 1 Shopee -> [ml, ml, ml, shopee]; 2 : 2 -> [ml, shopee, ml, shopee]."""
    ml, sh = grupo.peso_ml, grupo.peso_shopee
    if ml + sh == 0:
        ml = sh = 1
    seq, a, b = [], 0, 0
    while a < ml or b < sh:  # espalha a loja menor entre as da maior
        if b < sh and (a >= ml or (b + 1) * ml < (a + 1) * sh):
            seq.append("shopee"); b += 1
        else:
            seq.append("ml"); a += 1
    return seq


def candidatas_do_grupo(grupo: Grupo, n: int) -> list[Oferta]:
    """Candidatas da vez: a loja segue a proporção do grupo (padrão meio a meio);
    se a loja da vez não tiver oferta nova (ou estiver indisponível), usa a outra."""
    seq = sequencia_lojas(grupo)
    vez = _loja_da_vez.get(grupo.chave, 0) % len(seq)
    _loja_da_vez[grupo.chave] = vez + 1
    ordem = [_candidatas_ml, _candidatas_shopee]
    if seq[vez] == "shopee":
        ordem.reverse()
    for buscar in ordem:
        candidatas = buscar(grupo, n)
        if candidatas:
            return candidatas
    log.info("[%s] nenhuma oferta nova nas categorias do grupo", grupo.nome)
    return []


def _enviar(destino: Destino, grupos: list[Grupo], por_grupo: dict[str, list[Oferta]],
            n: int, registrar: bool) -> int:
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
    return enviadas


def executar_ciclo(destino: Destino, grupos: list[Grupo], registrar: bool = True) -> int:
    """Para cada grupo: coletar -> filtrar -> escolher; depois gera os links de
    afiliado de todos de uma vez e envia. Retorna o nº de ofertas enviadas."""
    if not dentro_do_horario():
        log.info("Fora do horário ativo (%s) — ciclo pulado", config.horario_ativo)
        return 0

    n = config.max_posts_por_ciclo
    # um Chrome só no ciclo inteiro (páginas de ofertas + Linkbuilder), aberto só se precisar;
    # ele fecha depois dos envios, porque fechar o Chrome pode demorar
    with afiliado_ml.chrome_compartilhado():
        por_grupo = {g.chave: candidatas_do_grupo(g, n) for g in grupos}
        todas = [o for lista in por_grupo.values() for o in lista]
        if todas:
            # link de afiliado é obrigatório: um único lote no Linkbuilder para todos os grupos
            com_link_afiliado(todas)
        enviadas = _enviar(destino, grupos, por_grupo, n, registrar)
        log.info("Ciclo: %d oferta(s) enviada(s) para %d grupo(s) (%s)",
                 enviadas, len(grupos), destino.nome)
    return enviadas
