"""Ofertas do Mercado Livre achadas por IA (ChatGPT, com pesquisa na web).

Sem confiar no que a IA diz:
1. De tempos em tempos (no máximo `buscas_por_dia`), o bot pede ao ChatGPT (API da
   OpenAI) que pesquise na web as melhores ofertas do Mercado Livre de agora (marcas,
   moda, calçados, perfumes, relógios, eletrônicos, ferramentas, casa, fitness…).
2. Cada produto sugerido é conferido na API oficial do ML (preço de agora, preço
   antigo, foto, se existe). O que não for achado na API é descartado: preço inventado
   ou produto que não existe nunca chega ao grupo.
3. O que passou entra no estoque das ofertas gerais (fonte "ia") e segue o caminho
   normal: filtros, sem repetir, link de afiliado e envio.

É pago por uso (tokens + pesquisas na web), cobrado pela OpenAI — a assinatura do
ChatGPT Plus não inclui a API. Fica desligado até ter a chave OPENAI_API_KEY no .env e
"ativa: true" em fontes.ia. Limites: buscas por dia e gasto máximo por mês (conta o
gasto real de cada busca em data/ia_ofertas.json).
"""
import datetime as dt
import json
import logging
import re
import time

from ..config import DATA_DIR, config
from ..models import Oferta

log = logging.getLogger("ofertas.ia")

ARQ_ESTADO = DATA_DIR / "ia_ofertas.json"
MODELO_PADRAO = "gpt-5-mini"
# US$ por milhão de tokens (entrada, saída) — confira em platform.openai.com/docs/pricing
PRECOS = {
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
}
FATOR_CACHE = 0.1               # tokens de entrada repetidos (cache) custam 10%
PRECO_PESQUISA = 10.00 / 1000   # US$ 10 a cada 1.000 pesquisas na web
# estimativa por busca (para mostrar o custo antes de ligar): tokens lidos por pesquisa
# (resultados das páginas) + o pedido, e tokens escritos (raciocínio + a lista)
TOKENS_ENTRADA_BASE = 3000
TOKENS_ENTRADA_POR_PESQUISA = 8000
TOKENS_SAIDA = 6000
DOMINIOS_PADRAO = ["mercadolivre.com.br", "pelando.com.br", "promobit.com.br"]
LINKS_DAS_PESQUISAS_MAX = 40  # links de produto achados nas pesquisas conferidos por busca
ARQ_ULTIMA_RESPOSTA = DATA_DIR / "ia_ultima_resposta.txt"  # diagnóstico da última busca
# link de produto do ML: anúncio (produto.mercadolivre.com.br/MLB-123…) ou catálogo (/p/MLB123)
_RE_LINK_ML = re.compile(
    r"https?://(?:produto\.mercadolivre\.com\.br/MLB-?\d{6,}[^\s\"'<>()\]]*"
    r"|(?:www\.)?mercadolivre\.com\.br/[^\s\"'<>()\]]*?/p/MLB\d{6,}[^\s\"'<>()\]]*)", re.I)


class ErroIA(RuntimeError):
    pass


def _modelo(valor) -> str:
    m = str(valor or "").strip()
    # config antiga (Claude) ou vazia: volta para o padrão do ChatGPT
    return m if m and not m.lower().startswith("claude") else MODELO_PADRAO


def opcoes() -> dict:
    o = config.fonte_ia or {}
    return {
        "ativa": bool(o.get("ativa", False)),
        "modelo": _modelo(o.get("modelo")),
        "buscas_por_dia": max(0, int(o.get("buscas_por_dia", 1))),
        "intervalo_horas": max(1.0, float(o.get("intervalo_horas", 4))),
        "pesquisas_por_busca": min(20, max(1, int(o.get("pesquisas_por_busca", 5)))),
        "produtos_por_busca": min(40, max(5, int(o.get("produtos_por_busca", 20)))),
        "gasto_max_mes_usd": max(0.0, float(o.get("gasto_max_mes_usd", 10))),
        "esforco": str(o.get("esforco") or "low"),
        "dominios": [str(d) for d in (o.get("dominios") or DOMINIOS_PADRAO)],
    }


def ligada() -> bool:
    return opcoes()["ativa"] and bool(config.openai_api_key)


# ── custo ────────────────────────────────────────────────────────────

def _precos(modelo: str) -> tuple[float, float]:
    return PRECOS.get(modelo, PRECOS[MODELO_PADRAO])


def custo_real(modelo: str, entrada: int, saida: int, pesquisas: int, cache_lida: int = 0) -> float:
    """`entrada` é o total de tokens lidos (a OpenAI conta os do cache dentro dele)."""
    pe, ps = _precos(modelo)
    cache_lida = min(cache_lida, entrada)
    return ((entrada - cache_lida) * pe + cache_lida * pe * FATOR_CACHE + saida * ps) / 1e6 \
        + pesquisas * PRECO_PESQUISA


def estimativa(op: dict | None = None) -> dict:
    """Custo estimado por busca, por dia e por mês (30 dias), em US$."""
    op = op or opcoes()
    n = op["pesquisas_por_busca"]
    por_busca = custo_real(op["modelo"], TOKENS_ENTRADA_BASE + n * TOKENS_ENTRADA_POR_PESQUISA,
                           TOKENS_SAIDA, n)
    dia = por_busca * op["buscas_por_dia"]
    mes = dia * 30
    if op["gasto_max_mes_usd"]:
        mes = min(mes, op["gasto_max_mes_usd"])
    return {"por_busca": round(por_busca, 3), "por_dia": round(dia, 2), "por_mes": round(mes, 2),
            "teto_mes": op["gasto_max_mes_usd"]}


# ── estado (buscas de hoje, gasto do mês) ────────────────────────────

def ler_estado() -> dict:
    try:
        return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _gravar_estado(e: dict) -> None:
    try:
        ARQ_ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def gasto_do_mes(estado: dict | None = None, hoje: dt.date | None = None) -> float:
    estado = ler_estado() if estado is None else estado
    mes = (hoje or dt.date.today()).strftime("%Y-%m")
    return float((estado.get("gasto_mes") or {}).get(mes, 0.0))


def motivo_para_nao_buscar(agora: float | None = None) -> str | None:
    """Por que a IA não busca agora (None = pode buscar)."""
    op = opcoes()
    if not op["ativa"]:
        return "desligada"
    if not config.openai_api_key:
        return "sem OPENAI_API_KEY no .env"
    agora = agora or time.time()
    hoje = dt.date.fromtimestamp(agora)
    e = ler_estado()
    feitas = (e.get("buscas_dia") or {}).get(hoje.isoformat(), 0)
    if feitas >= op["buscas_por_dia"]:
        return f"limite de {op['buscas_por_dia']} buscas por dia atingido"
    if op["gasto_max_mes_usd"] and gasto_do_mes(e, hoje) >= op["gasto_max_mes_usd"]:
        return f"limite de gasto do mês (US$ {op['gasto_max_mes_usd']:.2f}) atingido"
    if agora - float(e.get("ultima", 0)) < op["intervalo_horas"] * 3600:
        return "aguardando o intervalo entre buscas"
    return None


def _registrar_busca(custo: float, agora: float) -> dict:
    e = ler_estado()
    hoje = dt.date.fromtimestamp(agora)
    dias = e.setdefault("buscas_dia", {})
    dias[hoje.isoformat()] = dias.get(hoje.isoformat(), 0) + 1
    for k in [k for k in dias if k < (hoje - dt.timedelta(days=40)).isoformat()]:
        del dias[k]
    meses = e.setdefault("gasto_mes", {})
    mes = hoje.strftime("%Y-%m")
    meses[mes] = round(meses.get(mes, 0.0) + custo, 4)
    e["ultima"] = agora
    _gravar_estado(e)
    return e


# ── pedido ao ChatGPT ────────────────────────────────────────────────

FORMATO_LISTA = {
    "type": "json_schema",
    "name": "ofertas",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "ofertas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Link do produto no mercadolivre.com.br"},
                        "titulo": {"type": "string"},
                        "preco": {"type": "number", "description": "Preço em promoção, em reais"},
                        "preco_original": {"type": "number", "description": "Preço antes, em reais (0 se não souber)"},
                    },
                    "required": ["url", "titulo", "preco", "preco_original"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["ofertas"],
        "additionalProperties": False,
    },
}


def _pedido(op: dict) -> str:
    hoje = dt.date.today().strftime("%d/%m/%Y")
    return (
        f"Hoje é {hoje}. Pesquise na web produtos em oferta no Mercado Livre Brasil agora, para "
        "um grupo de promoções no WhatsApp com homens e mulheres. Foque em produtos de marca "
        "conhecida com bom desconto e que vendem bem: tênis e calçados, roupas e bolsas, "
        "moda fitness, perfumes e beleza, relógios e acessórios, celulares e eletrônicos, "
        "informática, ferramentas, casa e cozinha, esportes. Evite comida, bebida alcoólica, "
        "livros, peças de carro, réplicas e produtos de bebê.\n\n"
        "Faça pesquisas que tragam páginas de PRODUTO do Mercado Livre (endereços "
        "produto.mercadolivre.com.br/MLB-... ou mercadolivre.com.br/.../p/MLB...), por exemplo "
        "com a marca e o tipo de produto (\"tênis Nike oferta mercado livre\", \"legging fitness "
        "promoção mercado livre\"). Sites de promoções (Pelando, Promobit) mostram o que está em alta.\n\n"
        "Um programa confere cada produto na API oficial do Mercado Livre (preço de agora, preço "
        "antigo, se existe) e descarta o que não bater. Por isso: não descarte um produto por "
        "dúvida no preço — informe o preço que viu (ou 0 se não viu). Copie o link exatamente "
        "como apareceu nos resultados da pesquisa; nunca monte um link.\n\n"
        f"Responda só com a lista (formato JSON pedido), com até {op['produtos_por_busca']} "
        "produtos diferentes que você encontrou."
    )


_PEDIDO_LISTA = ("Agora, sem pesquisar de novo, responda com a lista dos produtos do Mercado Livre "
                 "que apareceram nas suas pesquisas (link exatamente como apareceu).")


def _ferramenta_pesquisa(op: dict) -> dict:
    t = {"type": "web_search", "user_location": {"type": "approximate", "country": "BR"}}
    if op["dominios"]:
        t["filters"] = {"allowed_domains": op["dominios"]}
    return t


def _cliente():
    import openai
    return openai.OpenAI(api_key=config.openai_api_key, max_retries=2, timeout=600)


def _somar_uso(total: dict, resposta) -> None:
    uso = getattr(resposta, "usage", None)
    if uso is not None:
        total["entrada"] += getattr(uso, "input_tokens", 0) or 0
        total["saida"] += getattr(uso, "output_tokens", 0) or 0
        det = getattr(uso, "input_tokens_details", None)
        total["cache_lida"] += (getattr(det, "cached_tokens", 0) or 0) if det else 0
    total["pesquisas"] += sum(1 for item in (getattr(resposta, "output", None) or [])
                              if getattr(item, "type", "") == "web_search_call")


def _texto(resposta) -> str:
    texto = getattr(resposta, "output_text", None)
    if isinstance(texto, str) and texto:
        return texto
    partes = []
    for item in getattr(resposta, "output", None) or []:
        if getattr(item, "type", "") == "message":
            partes += [getattr(c, "text", "") or "" for c in getattr(item, "content", None) or []
                       if getattr(c, "type", "") == "output_text"]
    return "".join(partes)


def _recusou(resposta) -> bool:
    return any(getattr(c, "type", "") == "refusal"
               for item in getattr(resposta, "output", None) or [] if getattr(item, "type", "") == "message"
               for c in getattr(item, "content", None) or [])


def _sugestoes_da_resposta(resposta) -> list[dict] | None:
    texto = _texto(resposta)
    m = re.search(r"\{.*\}", texto, re.S)
    if m:
        try:
            return list(json.loads(m.group(0)).get("ofertas") or [])
        except (ValueError, AttributeError):
            pass
    return None


def _achatar(obj, saida: list | None = None) -> list:
    """Todos os valores de um item da resposta (dicts, listas, objetos do SDK), para achar
    os links que vieram nas pesquisas, em qualquer formato."""
    saida = [] if saida is None else saida
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    elif hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes)):
        obj = vars(obj)
    if isinstance(obj, dict):
        if isinstance(obj.get("url"), str):
            saida.append((obj["url"], str(obj.get("title") or obj.get("titulo") or "")))
        for v in obj.values():
            _achatar(v, saida)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _achatar(v, saida)
    elif isinstance(obj, str):
        saida.extend((m.group(0), "") for m in _RE_LINK_ML.finditer(obj))
    return saida


def links_das_pesquisas(conteudo) -> list[dict]:
    """Links de produto do ML que apareceram nos resultados das pesquisas e no texto da IA
    (endereços de verdade, vindos da internet), sem repetir o mesmo produto."""
    from ..afiliado_ml import extrair_id
    vistos, links = set(), []
    for url, titulo in _achatar(list(conteudo)):
        m = _RE_LINK_ML.match(url.strip())
        ident = extrair_id(url) if m else None
        if ident and ident not in vistos:
            vistos.add(ident)
            links.append({"url": m.group(0), "titulo": titulo, "preco": 0, "preco_original": 0})
    return links


def _juntar(lista: list[dict], achados: list[dict]) -> list[dict]:
    """Lista da IA primeiro; depois os links das pesquisas que não estão nela."""
    from ..afiliado_ml import extrair_id
    vistos = {extrair_id(str(s.get("url") or "")) for s in lista} - {None}
    extras = [a for a in achados if extrair_id(a["url"]) not in vistos]
    return list(lista) + extras[:LINKS_DAS_PESQUISAS_MAX]


def _texto_diagnostico(resposta, lista, achados, uso) -> str:
    linhas = [f"status: {getattr(resposta, 'status', '?')}",
              f"pesquisas: {uso['pesquisas']} · tokens lidos: {uso['entrada']} · escritos: {uso['saida']}",
              f"lista da IA: {'não veio' if lista is None else len(lista)}",
              f"links de produto do ML achados nas pesquisas: {len(achados)}"]
    linhas += [f"  {a['url']}" for a in achados[:60]]
    for item in getattr(resposta, "output", None) or []:
        tipo = getattr(item, "type", "")
        if tipo == "web_search_call":
            acao = getattr(item, "action", None)
            consulta = getattr(acao, "query", None) or getattr(acao, "url", None) or ""
            urls = [u for u, _ in _achatar(acao) if u.startswith("http")] if acao is not None else []
            linhas.append(f"pesquisa: {consulta[:200]} — {len(urls)} páginas " + " | ".join(urls[:12]))
    texto = _texto(resposta)
    if texto:
        linhas.append("texto: " + texto[:1500])
    return "\n".join(linhas) + "\n"


def _guardar_diagnostico(texto: str) -> None:
    try:
        ARQ_ULTIMA_RESPOSTA.write_text(texto, encoding="utf-8")
    except OSError:
        pass


def _mensagem_da_openai(e) -> str:
    """O texto que a OpenAI mandou no erro (o 'message' do corpo), sem o resto."""
    corpo = getattr(e, "body", None)
    if isinstance(corpo, dict) and corpo.get("message"):
        codigo = f" [{corpo['code']}]" if corpo.get("code") else ""
        return str(corpo["message"])[:300] + codigo
    return str(getattr(e, "message", e))[:300]


def _erro_da_api(e) -> ErroIA:
    import openai
    texto = _mensagem_da_openai(e)
    if isinstance(e, openai.AuthenticationError):
        return ErroIA("chave OPENAI_API_KEY inválida")
    if isinstance(e, openai.PermissionDeniedError):
        return ErroIA(f"a chave não tem permissão: {texto}")
    if isinstance(e, openai.RateLimitError):
        codigo = str(getattr(e, "code", None) or "")
        if codigo == "insufficient_quota" or codigo.startswith("credit") \
                or "quota" in texto.lower() or "no credits" in texto.lower():
            return ErroIA("sem créditos na conta da OpenAI (platform.openai.com > Billing). "
                          f"Resposta da OpenAI: {texto}")
        return ErroIA(f"limite de uso da API atingido. Resposta da OpenAI: {texto}")
    if isinstance(e, openai.BadRequestError):
        return ErroIA(f"pedido recusado pela API: {texto}")
    if isinstance(e, openai.APIStatusError):
        return ErroIA(f"erro da API ({e.status_code}): {texto}")
    return ErroIA("sem conexão com a API da OpenAI")


def pedir_sugestoes(op: dict | None = None) -> tuple[list[dict], dict]:
    """Pergunta ao ChatGPT. Devolve (sugestões cruas, uso: tokens, pesquisas, custo).

    Sugestões = a lista que a IA entrega + todos os links de produto do ML que vieram nas
    pesquisas (já pagas), para a conferência na API do ML. Se a IA terminar sem a lista e as
    pesquisas não tiverem link de produto, o bot pede só a lista, uma vez, sem pesquisar de novo."""
    import openai
    op = op or opcoes()
    cliente = _cliente()
    uso = {"entrada": 0, "saida": 0, "cache_lida": 0, "pesquisas": 0,
           "da_lista": 0, "das_pesquisas": 0, "diagnostico": ""}
    sugestoes: list[dict] = []
    try:
        resposta = cliente.responses.create(
            model=op["modelo"], input=_pedido(op),
            tools=[_ferramenta_pesquisa(op)], max_tool_calls=op["pesquisas_por_busca"],
            include=["web_search_call.action.sources"],
            reasoning={"effort": op["esforco"]},
            text={"format": FORMATO_LISTA}, max_output_tokens=16000,
        )
        _somar_uso(uso, resposta)
        conteudo = list(getattr(resposta, "output", None) or [])
        if _recusou(resposta):
            raise ErroIA("o modelo recusou o pedido")
        lista = _sugestoes_da_resposta(resposta)
        achados = links_das_pesquisas(conteudo)
        uso["diagnostico"] = _texto_diagnostico(resposta, lista, achados, uso)
        if not lista and not achados and uso["pesquisas"]:
            # pesquisou mas não entregou a lista: pede só a lista, sem pesquisar de novo
            resposta = cliente.responses.create(
                model=op["modelo"], previous_response_id=resposta.id, input=_PEDIDO_LISTA,
                reasoning={"effort": op["esforco"]}, text={"format": FORMATO_LISTA},
                max_output_tokens=16000,
            )
            _somar_uso(uso, resposta)
            conteudo += list(getattr(resposta, "output", None) or [])
            lista = _sugestoes_da_resposta(resposta)
            achados = links_das_pesquisas(conteudo)
            uso["diagnostico"] += "── pedido só da lista ──\n" + _texto_diagnostico(resposta, lista, achados, uso)
        uso["da_lista"], uso["das_pesquisas"] = len(lista or []), len(achados)
        sugestoes = _juntar(lista or [], achados)
    except openai.OpenAIError as e:
        raise _erro_da_api(e) from e
    finally:
        uso["custo"] = custo_real(op["modelo"], uso["entrada"], uso["saida"], uso["pesquisas"],
                                  uso["cache_lida"])
        if uso["diagnostico"]:
            _guardar_diagnostico(uso["diagnostico"] + f"custo: US$ {uso['custo']:.3f}\n")
    return sugestoes, uso


# ── conferência na API do ML ─────────────────────────────────────────

def _palavras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9à-ú]+", texto.lower()) if len(p) > 2}


def _parecidos(a: str, b: str) -> bool:
    pa, pb = _palavras(a), _palavras(b)
    if not pa or not pb:
        return False
    return len(pa & pb) / min(len(pa), len(pb)) >= 0.6


def conferir(sugestoes: list[dict], cliente=None) -> tuple[list[Oferta], int]:
    """Só fica o que a API do ML confirma (preço, foto e título vêm da API, não da IA).
    Devolve (ofertas conferidas, quantas foram descartadas)."""
    from ..afiliado_ml import extrair_id
    from .mercadolivre import _ofertas_de_produtos, _via_catalogo, cliente_padrao, item_para_oferta
    cliente = cliente or cliente_padrao()
    site = str(config.fonte_ml.get("site") or "MLB")
    conferidas: dict[str, Oferta] = {}
    descartadas = 0
    for s in sugestoes:
        url, titulo = str(s.get("url") or ""), str(s.get("titulo") or "").strip()
        ident = extrair_id(url) if "mercadoli" in url else None
        achada: Oferta | None = None
        try:
            if ident and re.search(r"/p/MLB", url, re.I):
                achada = next(iter(_ofertas_de_produtos(cliente, [ident])), None)
            elif ident:
                itens = cliente.itens([ident])
                achada = item_para_oferta(itens[0]) if itens else None
                if achada is None:  # às vezes o código é de produto de catálogo
                    achada = next(iter(_ofertas_de_produtos(cliente, [ident])), None)
            if achada is None and titulo:  # sem link bom: procura pelo nome no catálogo
                candidatas = _via_catalogo(cliente, site, titulo, 3)
                achada = next((o for o in candidatas if _parecidos(o.titulo, titulo)), None)
        except Exception as e:
            log.debug("IA: não conferi '%s': %s", titulo[:50], e)
            achada = None
        if achada is None or not achada.preco:
            descartadas += 1
            continue
        conferidas.setdefault(achada.id_produto, achada)
    return list(conferidas.values()), descartadas


# ── ciclo ────────────────────────────────────────────────────────────

def buscar(agora: float | None = None, forcar: bool = False) -> list[Oferta]:
    """Faz uma busca com a IA, se estiver na hora e dentro dos limites; guarda o que
    passou na conferência no estoque das ofertas gerais."""
    from . import ml_geral
    agora = agora or time.time()
    motivo = None if forcar else motivo_para_nao_buscar(agora)
    if motivo:
        log.debug("IA: sem busca agora (%s)", motivo)
        return []
    op = opcoes()
    uso = {"custo": 0.0, "pesquisas": 0}
    try:
        sugestoes, uso = pedir_sugestoes(op)
    except ErroIA as e:
        log.warning("IA: %s", e)
        # erro de chave/crédito: não tenta de novo antes do intervalo (não gasta à toa)
        _registrar_busca(0.0, agora)
        return []
    estado = _registrar_busca(uso["custo"], agora)
    ofertas, descartadas = conferir(sugestoes)
    ml_geral.guardar(ml_geral.FONTE_IA, ofertas, agora)
    mes = gasto_do_mes(estado, dt.date.fromtimestamp(agora))
    teto = f" de {op['gasto_max_mes_usd']:.2f}" if op["gasto_max_mes_usd"] else ""
    log.info("IA: %d da lista da IA + %d links das pesquisas, %d conferidas no ML (%d descartadas) · "
             "%d pesquisas · US$ %.3f (mês: US$ %.2f%s)", uso.get("da_lista", 0), uso.get("das_pesquisas", 0),
             len(ofertas), descartadas, uso.get("pesquisas", 0), uso["custo"], mes, teto)
    if not ofertas:
        log.warning("IA: nenhuma oferta conferida nesta busca — detalhes em data/ia_ultima_resposta.txt")
    return ofertas
