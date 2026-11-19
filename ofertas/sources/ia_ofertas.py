"""Ofertas do Mercado Livre achadas por IA (Claude, com pesquisa na web).

Como o amigo faz com o ChatGPT, mas sem confiar no que a IA diz:
1. De tempos em tempos (no máximo `buscas_por_dia`), o bot pede ao Claude que pesquise
   na web as melhores ofertas do Mercado Livre de agora (marcas, moda, calçados,
   perfumes, relógios, eletrônicos, ferramentas, casa, fitness…).
2. Cada produto sugerido é conferido na API oficial do ML (preço de agora, preço
   antigo, foto, se existe). O que não for achado na API é descartado: preço inventado
   ou produto que não existe nunca chega ao grupo.
3. O que passou entra no estoque das ofertas gerais (fonte "ia") e segue o caminho
   normal: filtros, sem repetir, link de afiliado e envio.

É pago por uso (tokens + pesquisas na web). Fica desligado até ter a chave
ANTHROPIC_API_KEY no .env e "ativa: true" em fontes.ia. Limites: buscas por dia e gasto
máximo por mês (conta o gasto real de cada busca em data/ia_ofertas.json).
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
MODELO_PADRAO = "claude-opus-5-5"
# US$ por milhão de tokens (entrada, saída) — tabela oficial da Anthropic (nov/2026)
PRECOS = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
PRECO_PESQUISA = 10.00 / 1000   # US$ 10 a cada 1.000 pesquisas na web
# estimativa por busca (para mostrar o custo antes de ligar): tokens lidos por pesquisa
# (resultados das páginas) + o pedido, e tokens escritos (raciocínio + a lista)
TOKENS_ENTRADA_BASE = 3000
TOKENS_ENTRADA_POR_PESQUISA = 8000
TOKENS_SAIDA = 4000
DOMINIOS_PADRAO = ["mercadolivre.com.br", "pelando.com.br", "promobit.com.br"]
CONTINUAR_MAX = 3  # vezes que o bot deixa a IA continuar uma busca longa (pause_turn)


class ErroIA(RuntimeError):
    pass


def opcoes() -> dict:
    o = config.fonte_ia or {}
    return {
        "ativa": bool(o.get("ativa", False)),
        "modelo": str(o.get("modelo") or MODELO_PADRAO),
        "buscas_por_dia": max(0, int(o.get("buscas_por_dia", 1))),
        "intervalo_horas": max(1.0, float(o.get("intervalo_horas", 4))),
        "pesquisas_por_busca": min(20, max(1, int(o.get("pesquisas_por_busca", 5)))),
        "produtos_por_busca": min(40, max(5, int(o.get("produtos_por_busca", 20)))),
        "gasto_max_mes_usd": max(0.0, float(o.get("gasto_max_mes_usd", 10))),
        "esforco": str(o.get("esforco") or "low"),
        "dominios": [str(d) for d in (o.get("dominios") or DOMINIOS_PADRAO)],
    }


def ligada() -> bool:
    return opcoes()["ativa"] and bool(config.anthropic_api_key)


# ── custo ────────────────────────────────────────────────────────────

def _precos(modelo: str) -> tuple[float, float]:
    return PRECOS.get(modelo, PRECOS[MODELO_PADRAO])


def custo_real(modelo: str, entrada: int, saida: int, pesquisas: int,
               cache_escrita: int = 0, cache_lida: int = 0) -> float:
    pe, ps = _precos(modelo)
    return (entrada * pe + cache_escrita * pe * 1.25 + cache_lida * pe * 0.1 + saida * ps) / 1e6 \
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
    if not config.anthropic_api_key:
        return "sem ANTHROPIC_API_KEY no .env"
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


# ── pedido ao Claude ─────────────────────────────────────────────────

FERRAMENTA_ENTREGA = {
    "name": "entregar_ofertas",
    "description": "Entrega a lista final de ofertas do Mercado Livre encontradas na pesquisa. "
                   "Chame uma vez, no fim.",
    "strict": True,
    "input_schema": {
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
        f"Hoje é {hoje}. Pesquise na web as melhores ofertas do Mercado Livre Brasil que estão "
        "valendo agora, para um grupo de promoções no WhatsApp com homens e mulheres. "
        "Prefira produtos de marca conhecida com 30% de desconto ou mais e que vendem bem: "
        "tênis e calçados, roupas e bolsas, perfumes e beleza, relógios e acessórios, "
        "celulares e eletrônicos, informática, ferramentas, casa e cozinha, esportes e fitness. "
        "Evite comida, bebida alcoólica, livros, peças de carro, réplicas e produtos de bebê. "
        "Sites de promoções (Pelando, Promobit) ajudam a achar o que está em alta, mas o link "
        "entregue precisa ser do próprio produto no mercadolivre.com.br (com o código MLB). "
        f"Entregue até {op['produtos_por_busca']} produtos diferentes chamando a ferramenta "
        "entregar_ofertas uma única vez, no fim. Não invente link nem preço: se não tiver "
        "certeza do link de um produto, deixe-o de fora."
    )


def _ferramenta_pesquisa(op: dict) -> dict:
    # Haiku usa a versão básica da pesquisa; os demais, a versão com filtro dinâmico
    tipo = "web_search_20250305" if "haiku" in op["modelo"] else "web_search_20260209"
    t = {"type": tipo, "name": "web_search", "max_uses": op["pesquisas_por_busca"],
         "user_location": {"type": "approximate", "country": "BR"}}
    if op["dominios"]:
        t["allowed_domains"] = op["dominios"]
    return t


def _cliente():
    import anthropic
    return anthropic.Anthropic(api_key=config.anthropic_api_key, max_retries=2, timeout=600)


def _somar_uso(total: dict, uso) -> None:
    if uso is None:
        return
    total["entrada"] += getattr(uso, "input_tokens", 0) or 0
    total["saida"] += getattr(uso, "output_tokens", 0) or 0
    total["cache_escrita"] += getattr(uso, "cache_creation_input_tokens", 0) or 0
    total["cache_lida"] += getattr(uso, "cache_read_input_tokens", 0) or 0
    stu = getattr(uso, "server_tool_use", None)
    total["pesquisas"] += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0


def _sugestoes_da_resposta(resposta) -> list[dict] | None:
    for bloco in resposta.content:
        if getattr(bloco, "type", "") == "tool_use" and getattr(bloco, "name", "") == "entregar_ofertas":
            entrada = bloco.input if isinstance(bloco.input, dict) else {}
            return list(entrada.get("ofertas") or [])
    # sem a ferramenta: tenta achar um JSON no texto
    texto = "".join(getattr(b, "text", "") for b in resposta.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", texto, re.S)
    if m:
        try:
            return list(json.loads(m.group(0)).get("ofertas") or [])
        except (ValueError, AttributeError):
            pass
    return None


def pedir_sugestoes(op: dict | None = None) -> tuple[list[dict], dict]:
    """Pergunta ao Claude. Devolve (sugestões cruas, uso: tokens, pesquisas, custo)."""
    import anthropic
    op = op or opcoes()
    cliente = _cliente()
    mensagens: list[dict] = [{"role": "user", "content": _pedido(op)}]
    uso = {"entrada": 0, "saida": 0, "cache_escrita": 0, "cache_lida": 0, "pesquisas": 0}
    sugestoes: list[dict] | None = None
    try:
        for _ in range(CONTINUAR_MAX + 1):
            pedido = dict(
                model=op["modelo"], max_tokens=16000,
                tools=[_ferramenta_pesquisa(op), FERRAMENTA_ENTREGA],
                messages=mensagens,
                output_config={"effort": op["esforco"]},
            )
            if "haiku" not in op["modelo"]:
                # se o modelo recusar o pedido, a Anthropic tenta de novo em outro modelo
                pedido.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
                resposta = cliente.beta.messages.create(**pedido)
            else:
                resposta = cliente.messages.create(**pedido)
            _somar_uso(uso, resposta.usage)
            if resposta.stop_reason == "pause_turn":  # pesquisa longa: deixa continuar
                mensagens.append({"role": "assistant", "content": resposta.content})
                continue
            if resposta.stop_reason == "refusal":
                raise ErroIA("o modelo recusou o pedido")
            sugestoes = _sugestoes_da_resposta(resposta)
            break
    except anthropic.AuthenticationError as e:
        raise ErroIA("chave ANTHROPIC_API_KEY inválida") from e
    except anthropic.PermissionDeniedError as e:
        raise ErroIA(f"a chave não tem permissão: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise ErroIA("limite de uso da API atingido (tente mais tarde)") from e
    except anthropic.BadRequestError as e:
        texto = str(e.message)
        if "credit" in texto.lower() or "billing" in texto.lower():
            raise ErroIA("sem créditos na conta da Anthropic (console.anthropic.com > Billing)") from e
        raise ErroIA(f"pedido recusado pela API: {texto[:200]}") from e
    except anthropic.APIStatusError as e:
        raise ErroIA(f"erro da API ({e.status_code}): {str(e.message)[:200]}") from e
    except anthropic.APIConnectionError as e:
        raise ErroIA("sem conexão com a API da Anthropic") from e
    finally:
        uso["custo"] = custo_real(op["modelo"], uso["entrada"], uso["saida"], uso["pesquisas"],
                                  uso["cache_escrita"], uso["cache_lida"])
    return sugestoes or [], uso


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
    log.info("IA: %d sugeridas, %d conferidas no ML (%d descartadas) · %d pesquisas · "
             "US$ %.3f (mês: US$ %.2f%s)", len(sugestoes), len(ofertas), descartadas,
             uso.get("pesquisas", 0), uso["custo"], mes, teto)
    return ofertas
