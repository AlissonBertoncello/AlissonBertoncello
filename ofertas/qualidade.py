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


# ── diversidade: não repetir a mesma categoria (nem a mesma marca) em seguida ──
# tipo de produto pelo título (o primeiro que bater); a ordem importa: "relógio smart"
# é acessório, "lavadora de alta pressão" é ferramenta, "kit cuecas" é roupa
CATEGORIAS = (
    ("calçados", r"\b(t[eê]nis|sapat[eê]nis|sapato|sand[aá]lia|chinelo|bota|rasteir|mocassim|slide|papete|chuteira|babuche|alpargata)"),
    ("acessórios", r"\b(rel[oó]gio|smartwatch|[oó]culos|bon[eé]|bolsa|mochila|carteira|cinto|pulseira|colar|brinco|anel|mala\b|necessaire|chap[eé]u|gorro)"),
    ("roupas", r"\b(camis|blusa|cal[cç]a|bermuda|short|vestido|jaqueta|moletom|agasalho|casaco|meia|cueca|suti[aã]|lingerie|regata|polo\b|conjunto|legging|top\b|pijama|t-shirt|saia|biqu[ií]ni|mai[oô])"),
    ("beleza e perfume", r"\b(perfume|eau de|col[oô]nia|desodorante|body splash|shampoo|condicionador|creme|hidratante|maquiag|batom|s[eé]rum|protetor solar|m[aá]scara (de reconstru|capilar|de hidrata|de nutri)|capilar|cabelos?\b|escova (rotativa|secadora|alisadora)|secador|prancha|chapinha|barbeador|aparador|depilador)"),
    ("ferramentas", r"\b(furadeira|parafusadeira|martelete|trena|chave|soquete|alicate|serra|esmerilhadeira|martelo|n[ií]vel|ferrament|lixadeira|lavadora de alta|compressor|tupia|multímetro|multimetro)"),
    ("eletrônicos", r"\b(fone|headphone|headset|caixa de som|celular|smartphone|iphone|galaxy|carregador|power ?bank|tablet|notebook|mouse|teclado|monitor|smart tv|\btv\b|echo|alexa|kindle|ssd|pendrive|c[aâ]mera|console|controle|playstation|xbox|airpods|projetor)"),
    ("casa e cozinha", r"\b(panela|frigideira|air ?fryer|fritadeira|liquidificador|cafeteira|jogo de cama|toalha|travesseiro|edredom|organizador|garrafa|copo|pote|aspirador|ventilador|lumin[aá]ria|l[aâ]mpada|tapete|cortina|faca|talher|micro-?ondas|batedeira|sanduicheira|geladeira|ar[- ]condicionado|cooktop|forno|espremedor|mixer|cadeira|colch[aã]o)"),
    ("fitness", r"\b(whey|creatina|suplemento|halter|anilha|academia|yoga|bicicleta ergom|esteira|el[aá]stico|caneleira|kettlebell)"),
)
PERDA_MESMA_CATEGORIA_ULTIMA = 45   # mesma categoria do último envio
PERDA_MESMA_CATEGORIA_RECENTE = 25  # mesma categoria de um dos últimos 3
PERDA_MESMA_MARCA_RECENTE = 20      # mesma marca de um dos últimos 3
RECENTES = 3


def categoria(titulo: str) -> str | None:
    t = (titulo or "").lower()
    return next((nome for nome, rx in CATEGORIAS if re.search(rx, t)), None)


def _marca_do_titulo(titulo: str) -> str | None:
    t = _normal(titulo)
    return next((m for m in marcas() if f" {m} " in t), None)


def nota_com_diversidade(o: Oferta, recentes: list[str]) -> float:
    """Nota de qualidade menos a perda por repetir a categoria/marca dos últimos envios
    (recentes: títulos, o mais recente primeiro). Nada é proibido: só muda a ordem."""
    pontos = nota(o)
    cat = categoria(o.titulo)
    cats = [categoria(t) for t in recentes[:RECENTES]]
    if cat:
        if cats and cats[0] == cat:
            pontos -= PERDA_MESMA_CATEGORIA_ULTIMA
        elif cat in cats:
            pontos -= PERDA_MESMA_CATEGORIA_RECENTE
    marca = marca_boa(o)
    if marca and marca in {_marca_do_titulo(t) for t in recentes[:RECENTES]}:
        pontos -= PERDA_MESMA_MARCA_RECENTE
    return pontos
