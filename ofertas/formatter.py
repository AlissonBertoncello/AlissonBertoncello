"""Texto da mensagem no formato do WhatsApp (*negrito*, ~riscado~).

    *GANCHO DO GRUPO EM CAIXA ALTA*        (frases do grupo, em rodízio)

    Título curto do produto
    De ~R$ 339~ por *R$ 281* no Pix 🔻17%
    💰 Você economiza *R$ 58*
    🚚 Frete grátis

    🛒 https://meli.la/...

    🤝 Manda pro parceiro que tá precisando!   (chamada do grupo)
    👉 https://chat.whatsapp.com/...
"""
import random
import re

from .models import Grupo, Oferta

CHAMADA_PADRAO = "💬 Manda essa oferta pra alguém que vai gostar!"
MAX_PALAVRAS_TITULO = 8
MAX_LETRAS_TITULO = 60

# palavras que não fazem sentido no fim de um título cortado
_LIGACOES = {"de", "da", "do", "das", "dos", "com", "para", "pra", "e", "em", "a", "o", "ou",
             "p/", "c/", "-", "+", "/", "|", "–", "—", ","}

_proximo_gancho: dict[str, int] = {}  # rodízio dos ganchos, por grupo


def preco_br(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def preco_curto(valor: float) -> str:
    """Sem centavos quando o valor é redondo: R$ 281 · R$ 1.299 · R$ 69,90."""
    if abs(valor - round(valor)) < 0.005:
        return "R$ " + f"{round(valor):,}".replace(",", ".")
    return preco_br(valor)


def titulo_curto(titulo: str, max_palavras: int = MAX_PALAVRAS_TITULO,
                 max_letras: int = MAX_LETRAS_TITULO) -> str:
    """Título do anúncio enxuto: sem parênteses, sem palavras repetidas, até ~8 palavras."""
    t = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", titulo or "").strip()
    palavras, vistas = [], set()
    for p in t.split():
        chave = p.lower().strip(",.;:!")
        if len(chave) > 2 and chave not in _LIGACOES and chave in vistas:
            continue  # "Rádio ... Rádio FM" -> uma vez só
        vistas.add(chave)
        palavras.append(p)
    curto = []
    for p in palavras:
        if len(curto) >= max_palavras or len(" ".join([*curto, p])) > max_letras:
            break
        curto.append(p)
    while curto and curto[-1].lower().strip(",.;:") in _LIGACOES:
        curto.pop()
    return " ".join(curto).strip(" ,-+/|") or (titulo or "")[:max_letras]


def proximo_gancho(grupo: Grupo | None) -> str:
    """Próxima frase de abertura do grupo (começa num ponto sorteado e segue em ordem)."""
    if not (grupo and grupo.ganchos):
        return ""
    i = _proximo_gancho.setdefault(grupo.chave, random.randrange(len(grupo.ganchos)))
    _proximo_gancho[grupo.chave] = i + 1
    return grupo.ganchos[i % len(grupo.ganchos)]


def montar_mensagem(o: Oferta, grupo: Grupo | None = None, gancho: str | None = None) -> str:
    if gancho is None:
        gancho = proximo_gancho(grupo)
    titulo = titulo_curto(o.titulo)
    linhas = [f"*{gancho}*", "", titulo] if gancho else [f"🔥 *{titulo}*"]

    extras = [x.strip() for x in (o.extra or "").split(" · ") if x.strip()]
    pix = " no Pix" if any("pix" in x.lower() for x in extras) else ""
    extras = [x for x in extras if "pix" not in x.lower()]

    if o.preco and o.preco_original and o.preco_original > o.preco:
        selo = f" 🔻{o.desconto}%" if o.desconto else ""
        linhas.append(f"De ~{preco_curto(o.preco_original)}~ por *{preco_curto(o.preco)}*{pix}{selo}")
        linhas.append(f"💰 Você economiza *{preco_curto(o.preco_original - o.preco)}*")
    elif o.preco:
        linhas.append(f"Por *{preco_curto(o.preco)}*{pix}")
    if extras:
        linhas.append(" · ".join(extras))

    linhas += ["", f"🛒 {o.link}"]
    if grupo and grupo.convite:
        linhas += ["", grupo.chamada or CHAMADA_PADRAO, f"👉 {grupo.convite}"]
    return "\n".join(linhas)
