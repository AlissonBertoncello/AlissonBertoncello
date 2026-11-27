"""Nota de qualidade das ofertas (grupos de ofertas gerais): o bot manda a de nota mais
alta, não a primeira que passa nos filtros.

nota = desconto (até 80) + 40 se for de marca conhecida + até 20 pela posição no ranking
de mais vendidos (1º = 20) + 10 se o preço estiver entre R$ 60 e R$ 1.500.
Produto sem marca conhecida não é proibido: só perde para um de marca.
A lista de marcas pode ganhar mais nomes em filtros.marcas_boas (painel, Envio e filtros).
"""
import re
import unicodedata

from .config import config
from .models import Oferta

PONTOS_MARCA = 40
FAIXA_PRECO_BOA = (60.0, 1500.0)

MARCAS_PADRAO = (
    # calçados, roupas e esporte
    "nike", "adidas", "puma", "olympikus", "mizuno", "asics", "fila", "new balance", "vans",
    "converse", "all star", "reebok", "under armour", "skechers", "jordan", "havaianas", "ipanema",
    "melissa", "crocs", "rider", "kappa", "umbro", "penalty", "oakley", "lacoste", "tommy hilfiger",
    "calvin klein", "levis", "levi's", "hering", "colcci", "aramis", "polo wear",
    "ralph lauren", "diesel", "hugo boss", "osklen", "arezzo", "schutz", "vizzano",
    "moleca", "beira rio", "usaflex", "piccadilly", "democrata", "ferracini", "pegada", "kipling",
    "samsonite", "mormaii", "speedo", "lupo", "insider", "puket", "torx",
    # relógios, óculos e acessórios
    "casio", "g-shock", "technos", "orient", "seiko", "citizen", "invicta", "fossil", "michael kors",
    "mondaine", "ray-ban", "rayban", "chilli beans", "pandora", "vivara", "swarovski",
    # perfumes e beleza
    "natura", "boticario", "o boticario", "eudora", "avon", "malbec", "egeo", "kaiak",
    "carolina herrera", "paco rabanne", "dior", "chanel", "lancome", "givenchy",
    "azzaro", "antonio banderas", "nivea", "loreal", "l'oreal", "elseve",
    "pantene", "dove", "neutrogena", "la roche-posay", "vichy", "cerave", "bioderma", "salon line",
    "wella", "truss", "braé", "kerastase", "taiff", "gama italy", "philco", "britania", "mondial",
    "philips", "oral-b", "gillette", "remington", "wahl",
    # eletrônicos e informática
    "samsung", "apple", "iphone", "xiaomi", "redmi", "motorola", "lg", "sony", "jbl", "harman",
    "bose", "edifier", "multilaser", "intelbras", "positivo", "dell", "lenovo", "acer", "asus",
    "hp", "logitech", "redragon", "hyperx", "razer", "kingston", "sandisk", "seagate", "tp-link",
    "amazfit", "huawei", "lenoxx", "philips walita", "baseus", "anker", "ugreen", "aiwa",
    "playstation", "xbox", "nintendo", "gopro", "canon", "nikon", "amazon", "echo dot", "kindle",
    "soundcore", "anker", "wap",
    # casa, cozinha e eletroportáteis
    "tramontina", "electrolux", "brastemp", "consul", "arno", "oster", "black+decker",
    "black decker", "cadence", "wap", "electrolux", "midea", "panasonic", "nespresso",
    "dolce gusto", "tefal", "rochedo", "brinox", "oxford", "polishop", "kitchenaid", "fischer",
    "mallory", "ventisol", "britânia", "elgin", "karcher", "kärcher",
    # ferramentas
    "bosch", "makita", "dewalt", "stanley", "vonder", "tramontina pro", "black and decker",
    "einhell", "worx", "skil", "irwin", "gedore", "wurth", "würth", "starrett", "intech machine",
    # fitness e suplementos
    "growth", "max titanium", "integralmedica", "integral medica", "probiotica", "dux",
    "darkness", "black skull", "optimum nutrition", "atlhetica", "kikos",
)


def _normal(texto: str) -> str:
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"[^a-z0-9+'&-]+", " ", texto).strip() + " "


def marcas() -> list[str]:
    extras = [str(m) for m in (getattr(config, "marcas_boas", None) or [])]
    return list(dict.fromkeys(_normal(m).strip() for m in (*MARCAS_PADRAO, *extras) if str(m).strip()))


def marca_boa(o: Oferta) -> str | None:
    """A marca conhecida do produto (pela ficha do ML ou pelo título), ou None."""
    lista = marcas()
    if getattr(o, "marca", None):
        m = _normal(o.marca).strip()
        if m in lista:
            return m
    titulo = _normal(o.titulo)
    return next((m for m in lista if f" {m} " in titulo), None)


def nota(o: Oferta) -> float:
    pontos = float(min(o.desconto or 0, 80))
    if marca_boa(o):
        pontos += PONTOS_MARCA
    if o.posicao:
        pontos += max(0, 21 - o.posicao)
    if o.preco and FAIXA_PRECO_BOA[0] <= o.preco <= FAIXA_PRECO_BOA[1]:
        pontos += 10
    return pontos


def e_marca(termo: str) -> bool:
    return _normal(termo).strip() in marcas()
