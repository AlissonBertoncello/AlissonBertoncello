import datetime as dt
import logging
import re
import socket
import time
from collections import Counter

from . import afiliado_ml, cupons, db
from .config import config, dentro_do_horario
from .destinos import Destino
from .formatter import montar_mensagem
from .models import Grupo, Oferta
from .sources import ia_ofertas, mercadolivre, ml_geral, shopee

log = logging.getLogger("ofertas.pipeline")


class SemInternet(RuntimeError):
    """O notebook ficou sem internet (dormiu ou a rede caiu): o ciclo para e tenta de novo logo."""


_HOSTS_TESTE = ("api.mercadolibre.com", "open-api.affiliate.shopee.com.br", "www.google.com")


def rede_ok() -> bool:
    """True se o notebook consegue achar pelo menos um dos sites (DNS respondendo)."""
    for host in _HOSTS_TESTE:
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            continue
    return False


def _checar_rede() -> None:
    if not rede_ok():
        raise SemInternet("sem internet")


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


TOP_SEM_DESCONTO = 5  # "mais vendido sem desconto também vale": só os 5 primeiros do ranking


def motivo_descarte(o: Oferta, grupo: str, bloquear: list[str] = (),
                    sem_desconto: bool = False) -> str | None:
    """Por que a oferta não serve para o grupo (None = serve).
    sem_desconto: aceita os primeiros do ranking de mais vendidos sem preço antigo ("Por R$ X")."""
    if not o.titulo:
        return "sem título"
    if db.ja_enviada(o.uid, config.nao_repetir_dias, grupo, o.titulo):
        return "já enviadas"
    if config.desconto_minimo and (o.desconto or 0) < config.desconto_minimo:
        campeao = sem_desconto and o.desconto is None and o.posicao and o.posicao <= TOP_SEM_DESCONTO
        if not campeao:
            return f"desconto < {config.desconto_minimo}%"
    if o.preco is not None:
        if config.preco_minimo and o.preco < config.preco_minimo:
            return "preço baixo"
        if config.preco_maximo and o.preco > config.preco_maximo:
            return "preço alto"
    if tem_palavra_bloqueada(o.titulo, bloquear):
        return "palavra bloqueada"
    return None


# ── repetição de produto parecido ────────────────────────────────────

# palavras que aparecem em quase tudo do nicho e não dizem que tipo de produto é
_GENERICAS = {
    "kit", "kits", "unidade", "unidades", "peça", "peças", "pecas", "original", "novo", "nova",
    "feminino", "feminina", "masculino", "masculina", "infantil", "bebê", "bebe", "bebês", "adulto",
    "automotivo", "automotiva", "carro", "carros", "veículo", "veicular", "moto", "para", "com",
    "sem", "mais", "promoção", "oferta", "premium", "profissional", "qualidade", "envio", "entrega",
    "rápida", "rapida", "pronta", "cores", "branco", "branca", "preto", "preta", "azul", "rosa",
    "verde", "vermelho", "cinza", "grande", "pequeno", "pequena", "tamanho", "unissex", "menino",
    "menina", "linha", "marca", "modelo", "tipo", "conjunto", "litro", "litros",
}
_UNIDADE = re.compile(r"^\d+([.,]\d+)?(ml|l|lt|g|gr|kg|mg|w|v|cm|mm|m|mt|mah|gb|tb|un|und|unid|pcs|"
                      r"pçs|x|hz|k|rms|pol|p|cv|em\d+)$")
PARECIDAS_ULTIMAS = 4  # não manda em seguida algo parecido com os últimos N envios do grupo


def _radicais(titulo: str) -> set[str]:
    """'Shampoo Automotivo V-Floc Vonixx' -> {'shamp', 'vonix'} (sem números e palavras genéricas)."""
    return {p[:5] for p in re.findall(r"[^\W\d_]+", (titulo or "").lower())
            if len(p) >= 4 and p not in _GENERICAS}


def parecida(titulo: str, outros: list[str]) -> bool:
    """Mesmo tipo de produto de algum dos `outros` (2+ palavras importantes em comum)."""
    meus = _radicais(titulo)
    return any(len(meus & _radicais(t)) >= 2 for t in outros)


def modelos(titulo: str) -> set[str]:
    """Códigos de modelo do título: 'Stetsom STX 2448' e 'STX2448' -> {'stx2448'}."""
    juntos = re.sub(r"\b([A-Z]{2,4})[ -](\d{3,})\b", r"\1\2", titulo or "")
    achados = set()
    for t in re.findall(r"[a-z0-9]+", juntos.lower()):
        if len(t) >= 4 and re.search(r"\d", t) and re.search(r"[a-z]", t) \
                and not _UNIDADE.match(t) and not re.match(r"^\d+x\d+", t):
            achados.add(t)
    return achados


def filtrar(ofertas: list[Oferta], grupo: str, bloquear: list[str] = (),
            motivos: Counter | None = None, sem_desconto: bool = False) -> list[Oferta]:
    """Ofertas que passam nos filtros; em `motivos` conta por que as outras saíram."""
    aprovadas = []
    enviados = set()  # modelos já enviados ao grupo no prazo de não repetir
    if ofertas and config.nao_repetir_dias:
        for t in db.titulos_desde(grupo, config.nao_repetir_dias):
            enviados |= modelos(t)
    for o in ofertas:
        motivo = motivo_descarte(o, grupo, bloquear, sem_desconto)
        if motivo is None and enviados & modelos(o.titulo):
            motivo = "já enviadas"  # mesmo modelo em outro anúncio
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


def com_link_afiliado(ofertas: list[Oferta], etiqueta: str = "") -> list[Oferta]:
    """Gera os links de afiliado (só das candidatas: o Linkbuilder é caro) e
    descarta as que ficaram sem link: oferta sem link de afiliado nunca é enviada.
    A Shopee já devolve o link de afiliado pronto; o Linkbuilder é só do Mercado Livre."""
    do_ml = [o for o in ofertas if o.plataforma == "mercadolivre"]
    if do_ml:
        try:
            if etiqueta:  # etiqueta só do grupo: link rastreável por grupo
                afiliado_ml.gerar_links_afiliado(do_ml, etiqueta)
            else:
                afiliado_ml.gerar_links_afiliado(do_ml)
        except Exception as e:
            _checar_rede()
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
_shopee_falhou: set[str] = set()       # grupos em que a Shopee deu erro neste ciclo
TENTATIVAS_SHOPEE = 3                  # palavras tentadas por ciclo antes de desistir
_estat_shopee = {"dia": "", "ok": 0, "erro": 0, "resumido": False}


def ordem_espalhada(n: int) -> list[int]:
    """Ordem do rodízio intercalando as duas metades da lista: [0, 2, 1, 3] para 4 itens.
    Listas costumam ter itens parecidos em sequência (3 de limpeza, depois 3 de roupa…);
    assim o grupo não recebe o mesmo tipo de produto várias vezes seguidas."""
    meio = (n + 1) // 2
    ordem = []
    for i in range(meio):
        ordem.append(i)
        if meio + i < n:
            ordem.append(meio + i)
    return ordem


def _separar_parecidas(grupo: Grupo, candidatas: list[Oferta], onde: str) -> tuple[list[Oferta], list[Oferta]]:
    """(diferentes, parecidas) em relação aos últimos envios do grupo."""
    recentes = db.ultimos_titulos(grupo.chave, PARECIDAS_ULTIMAS)
    diferentes = [o for o in candidatas if not parecida(o.titulo, recentes)]
    parecidas = [o for o in candidatas if o not in diferentes]
    if parecidas and not diferentes:
        log.info("[%s] %s: só ofertas parecidas com as últimas enviadas — tentando a próxima", grupo.nome, onde)
    return diferentes, parecidas


def _contar_shopee(ok: bool) -> None:
    hoje = dt.date.today().isoformat()
    if _estat_shopee["dia"] != hoje:
        resumo_shopee()
        _estat_shopee.update(dia=hoje, ok=0, erro=0, resumido=False)
    _estat_shopee["ok" if ok else "erro"] += 1


def resumo_shopee() -> None:
    """Uma linha por dia com quantas buscas na Shopee funcionaram."""
    e = _estat_shopee
    if e["dia"] and not e["resumido"] and (e["ok"] or e["erro"]):
        log.info("Shopee em %s: %d buscas ok, %d com erro da Shopee", e["dia"], e["ok"], e["erro"])
        e["resumido"] = True


def _melhores(grupo: Grupo, brutas: list[Oferta], rotulo: str, n: int) -> tuple[list[Oferta], list[Oferta]]:
    """Filtra e escolhe as candidatas de uma fonte: (para enviar, só parecidas com as últimas)."""
    motivos = Counter()
    boas = filtrar(brutas, grupo.chave, grupo.bloquear, motivos, grupo.sem_desconto)
    log.info("[%s] %s: %s", grupo.nome, rotulo, _resumo(brutas, boas, motivos))
    # reservas: se uma ficar sem link de afiliado, a próxima melhor entra no lugar
    candidatas = escolher(boas, n * 3)
    if not candidatas:
        return [], []
    diferentes, parecidas = _separar_parecidas(grupo, candidatas, rotulo)
    return (diferentes + parecidas if diferentes else []), parecidas


def _fonte_automatica(grupo: Grupo, n: int) -> tuple[list[Oferta], list[Oferta]]:
    """Ofertas gerais pela API do ML: termos mais buscados agora (em alta) no catálogo;
    depois as subcategorias de cada departamento em rodízio — o ranking de mais vendidos
    e o catálogo pelo nome da subcategoria."""
    cliente = mercadolivre.cliente_padrao()
    try:
        vez = ml_geral.da_vez(grupo, cliente)
    except Exception as e:
        _checar_rede()
        log.warning("[%s] Mercado Livre (mais vendidos): %s", grupo.nome, e)
        return [], []
    reserva: list[Oferta] = []
    # primeiro: termos mais buscados agora no ML (em alta), procurados no catálogo
    try:
        alta = ml_geral.em_alta_da_vez(grupo, cliente)
    except Exception as e:
        log.debug("[%s] Em alta no ML: %s", grupo.nome, e)
        alta = []
    for termo in alta:
        try:
            brutas = ml_geral.catalogo(termo, cliente)
        except Exception as e:
            _checar_rede()
            log.debug("[%s] Em alta '%s': %s", grupo.nome, termo, e)
            continue
        achadas, parecidas = _melhores(grupo, brutas, f"Em alta no ML '{termo}'", n)
        if achadas:
            return achadas, []
        reserva = reserva or parecidas
    for cid, nome in vez:
        for rotulo, buscar in ((f"Mais vendidos '{nome}'", lambda: ml_geral.mais_vendidos(cid, cliente)),
                               (f"Catálogo do ML '{nome}'", lambda: ml_geral.catalogo(nome, cliente))):
            try:
                brutas = buscar()
            except Exception as e:
                _checar_rede()
                log.debug("[%s] %s: %s", grupo.nome, rotulo, e)
                continue
            achadas, parecidas = _melhores(grupo, brutas, rotulo, n)
            if achadas:
                return achadas, []
            reserva = reserva or parecidas
    return [], reserva


def _das_categorias(grupo: Grupo, n: int) -> tuple[list[Oferta], list[Oferta]]:
    """Categorias do grupo, a partir da do rodízio: (para enviar, só parecidas)."""
    cats = list(grupo.categorias.items())
    if not cats:
        return [], []
    ordem = ordem_espalhada(len(cats))
    inicio = _proxima.get(grupo.chave, 0) % len(cats)
    reserva: list[Oferta] = []
    pos_reserva = None
    for passo in range(len(cats)):
        pos = (inicio + passo) % len(cats)
        cid, nome = cats[ordem[pos]]
        brutas = coletar({cid: nome})
        if not brutas:
            _checar_rede()  # nada veio: se for falta de internet, para o ciclo aqui
        achadas, parecidas = _melhores(grupo, brutas, nome, n)
        if achadas:
            _proxima[grupo.chave] = pos + 1
            return achadas, []
        if parecidas and not reserva:
            reserva, pos_reserva = parecidas, pos
    _proxima[grupo.chave] = (inicio if pos_reserva is None else pos_reserva) + 1
    return [], reserva


def _candidatas_ml(grupo: Grupo, n: int) -> list[Oferta]:
    """Grupo com ofertas gerais: estoque (ofertas da IA conferidas no ML) -> mais vendidos e
    catálogo do ML automáticos -> categorias do grupo. Grupo comum: categorias do grupo.
    Pula a fonte sem oferta nova (ou só com produto parecido com os últimos enviados)."""
    if not config.fonte_ml.get("ativa"):
        return []
    reserva: list[Oferta] = []  # parecidas com as últimas: só se não houver outra
    fontes = [_das_categorias]
    if grupo.ofertas_gerais:
        achadas, reserva = _melhores(grupo, ml_geral.ofertas_para(grupo), "Ofertas gerais do ML", n)
        if achadas:
            return achadas
        fontes = [_fonte_automatica, _das_categorias]
    for fonte in fontes:
        achadas, parecidas = fonte(grupo, n)
        if achadas:
            return achadas
        reserva = reserva or parecidas
    return reserva


# lista de mais vendidos da Shopee (sem palavra-chave) para os grupos de ofertas gerais
PAGINAS_LISTA_SHOPEE = 10
_pagina_lista_shopee: dict[str, int] = {}
_lista_shopee_recusada: set[str] = set()  # a Shopee recusou a consulta: não tenta mais nesta execução


def _usa_lista_shopee(grupo: Grupo) -> bool:
    return grupo.ofertas_gerais and not grupo.departamentos and "lista" not in _lista_shopee_recusada


def _da_lista_shopee(grupo: Grupo, n: int) -> list[Oferta]:
    """Próxima página da lista de mais vendidos da Shopee (todas as categorias)."""
    pagina = _pagina_lista_shopee.get(grupo.chave, 0) % PAGINAS_LISTA_SHOPEE + 1
    _pagina_lista_shopee[grupo.chave] = pagina
    try:
        brutas = shopee.mais_vendidos(pagina)
    except Exception as e:
        if getattr(e, "rede", False):
            _checar_rede()
        _contar_shopee(False)
        if not getattr(e, "passageiro", False):
            _lista_shopee_recusada.add("lista")
            log.warning("Shopee não aceitou a lista de mais vendidos (%s) — usando só as palavras-chave", e)
        else:
            log.warning("[%s] Shopee mais vendidos: %s", grupo.nome, e)
        return []
    _contar_shopee(True)
    achadas, parecidas = _melhores(grupo, brutas, f"Shopee mais vendidos (página {pagina})", n)
    return achadas or parecidas


def _shopee_disponivel(grupo: Grupo) -> bool:
    if not ((grupo.shopee or _usa_lista_shopee(grupo)) and config.fonte_shopee.get("ativa")):
        return False
    if not shopee.tem_credenciais():
        if "credenciais" not in _avisou_shopee:
            _avisou_shopee.add("credenciais")
            log.warning("Shopee: sem SHOPEE_APP_ID/SHOPEE_APP_SECRET no .env — usando só o "
                        "Mercado Livre por enquanto")
        return False
    return True


def _candidatas_shopee(grupo: Grupo, n: int) -> list[Oferta]:
    """Palavra-chave da vez na Shopee; se der erro ou não render oferta nova, tenta mais algumas."""
    if not _shopee_disponivel(grupo):
        return []
    if _usa_lista_shopee(grupo):
        candidatas = _da_lista_shopee(grupo, n)
        if candidatas:
            return candidatas
    termos = grupo.shopee
    if not termos:
        return []
    ordem = ordem_espalhada(len(termos))
    inicio = _proxima_shopee.get(grupo.chave, 0) % len(termos)
    tentativas = min(TENTATIVAS_SHOPEE, len(termos))
    erros = 0
    reserva: tuple[int, list[Oferta]] | None = None
    for passo in range(tentativas):
        pos = (inicio + passo) % len(termos)
        termo = termos[ordem[pos]]
        try:
            brutas = shopee.buscar(termo)
        except Exception as e:
            if getattr(e, "rede", False):
                _checar_rede()
            _contar_shopee(False)
            erros += 1 if getattr(e, "passageiro", True) else 0
            log.warning("[%s] Shopee '%s': %s", grupo.nome, termo, e)
            continue
        _contar_shopee(True)
        motivos = Counter()
        boas = filtrar(brutas, grupo.chave, grupo.bloquear, motivos, grupo.sem_desconto)
        log.info("[%s] Shopee '%s': %s", grupo.nome, termo, _resumo(brutas, boas, motivos))
        candidatas = escolher(boas, n * 3)
        if not candidatas:
            continue
        diferentes, parecidas = _separar_parecidas(grupo, candidatas, f"Shopee '{termo}'")
        if diferentes:
            _proxima_shopee[grupo.chave] = pos + 1
            return diferentes + parecidas
        reserva = reserva or (pos, parecidas)
    if reserva:
        _proxima_shopee[grupo.chave] = reserva[0] + 1
        return reserva[1]
    _proxima_shopee[grupo.chave] = inicio + tentativas
    if erros == tentativas:  # todas com falha passageira do lado da Shopee
        _shopee_falhou.add(grupo.chave)
        log.warning("[%s] Shopee com erro nas %d tentativas — este ciclo vai de Mercado Livre e a vez "
                    "da Shopee fica para o próximo", grupo.nome, erros)
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
    _shopee_falhou.discard(grupo.chave)
    ordem = [_candidatas_ml, _candidatas_shopee]
    if seq[vez] == "shopee":
        ordem.reverse()
    for buscar in ordem:
        candidatas = buscar(grupo, n)
        if candidatas:
            if seq[vez] == "shopee" and grupo.chave in _shopee_falhou:
                _loja_da_vez[grupo.chave] = vez  # a Shopee deu erro: a vez dela fica guardada
            return candidatas
    log.info("[%s] nenhuma oferta nova nas categorias do grupo", grupo.nome)
    return []


def _pausar(destino: Destino, estado: dict) -> None:
    """Pausa entre envios (inclusive de grupos diferentes): ritmo mais humano no WhatsApp."""
    if estado["enviadas"] + estado["cupons"] and destino.nome != "console":
        time.sleep(max(0.0, config.espacamento_segundos - (time.monotonic() - estado["ultimo"])))


def _link_shopee_do_grupo(o: Oferta, g: Grupo) -> None:
    """Link da Shopee com o grupo como Sub ID (o relatório da Shopee mostra de qual grupo veio
    cada clique/venda). Se a Shopee não gerar, fica o link de afiliado normal."""
    if not o.url_produto or o.url_produto == o.url_afiliado:
        return
    try:
        o.url_afiliado = shopee.link_afiliado(o.url_produto, sub_id=g.chave)
    except Exception as e:
        log.debug("[%s] link da Shopee por grupo não gerado (%s) — usando o normal", g.nome, e)


def _enviar(destino: Destino, grupos: list[Grupo], por_grupo: dict[str, list[Oferta]],
            n: int, registrar: bool, estado: dict) -> None:
    for g in grupos:
        candidatas = por_grupo[g.chave]
        escolhidas = [o for o in candidatas if o.url_afiliado][:n]
        if candidatas and not escolhidas:
            log.error("[%s] nenhuma oferta enviada: não foi possível gerar link de afiliado "
                      "(motivo na linha 'Linkbuilder ML falhou' acima)", g.nome)
        for o in escolhidas:
            if o.plataforma == "shopee":
                _link_shopee_do_grupo(o, g)
            _pausar(destino, estado)
            try:
                destino.enviar(o, montar_mensagem(o, g), g)
            except Exception as e:
                log.error("[%s] falha ao enviar '%s': %s", g.nome, o.titulo[:60], e)
                continue
            estado["ultimo"] = time.monotonic()
            if registrar:
                db.registrar(o, g.chave)
            estado["enviadas"] += 1


def _enviar_cupons(destino: Destino, posts: list, registrar: bool, estado: dict) -> None:
    for post in posts:
        _pausar(destino, estado)
        try:
            destino.enviar(post.oferta, post.mensagem, post.grupo)
        except Exception as e:
            log.error("[%s] falha ao enviar o cupom '%s': %s", post.grupo.nome, post.oferta.titulo[:60], e)
            continue
        estado["ultimo"] = time.monotonic()
        estado["cupons"] += 1
        if registrar:
            cupons.registrar(post)


def executar_ciclo(destino: Destino, grupos: list[Grupo], registrar: bool = True) -> int:
    """Para cada grupo: coletar -> filtrar -> escolher; depois gera os links de
    afiliado de todos de uma vez e envia; nos horários de cupom, posta também um cupom.
    Retorna o nº de ofertas enviadas (sem contar os cupons).
    Sem internet, para na hora com SemInternet (o bot tenta de novo em poucos minutos)."""
    if not dentro_do_horario():
        resumo_shopee()
        log.info("Fora do horário ativo (%s) — ciclo pulado", config.horario_ativo)
        return 0
    _checar_rede()

    n = config.max_posts_por_ciclo
    estado = {"enviadas": 0, "cupons": 0, "ultimo": 0.0}
    if config.fonte_ml.get("ativa"):
        try:  # antes do Chrome do ciclo: a página geral usa um Chrome (e perfil) próprio
            ml_geral.atualizar(grupos)
        except Exception as e:
            log.error("Ofertas gerais do ML: %s", e)
        if any(g.ofertas_gerais for g in grupos) and ia_ofertas.ligada():
            try:  # ofertas achadas pela IA e conferidas na API do ML (só na hora e no limite)
                ia_ofertas.buscar()
            except Exception as e:
                log.error("IA: %s", e)
    # um Chrome só no ciclo inteiro (páginas de ofertas + Linkbuilder), aberto só se precisar;
    # ele fecha depois dos envios, porque fechar o Chrome pode demorar
    with afiliado_ml.chrome_compartilhado():
        por_grupo = {g.chave: candidatas_do_grupo(g, n) for g in grupos}
        # link de afiliado é obrigatório: um lote no Linkbuilder para todos os grupos
        # (um por etiqueta, quando um grupo tem etiqueta própria)
        por_etiqueta: dict[str, list[Oferta]] = {}
        for g in grupos:
            por_etiqueta.setdefault(g.etiqueta_ml, []).extend(por_grupo[g.chave])
        for etiqueta, lista in por_etiqueta.items():
            if lista:
                com_link_afiliado(lista, etiqueta)
        _enviar(destino, grupos, por_grupo, n, registrar, estado)
        try:
            posts = cupons.da_vez(grupos, registrar=registrar)
        except Exception as e:
            log.error("Cupons: %s", e)
            posts = []
        _enviar_cupons(destino, posts, registrar, estado)
        extra = f" + {estado['cupons']} cupom(ns)" if estado["cupons"] else ""
        log.info("Ciclo: %d oferta(s)%s enviada(s) para %d grupo(s) (%s)",
                 estado["enviadas"], extra, len(grupos), destino.nome)
    return estado["enviadas"]
