"""Texto da mensagem no formato do WhatsApp (*negrito*, ~riscado~)."""
from .models import Oferta

_PLATAFORMA = {
    "mercadolivre": "💛 Mercado Livre",
}


def preco_br(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def montar_mensagem(o: Oferta) -> str:
    linhas = [f"🔥 *{o.titulo[:180]}*", ""]

    selo = f"  🔻 *-{o.desconto}%*" if o.desconto else ""
    if o.preco and o.preco_original and o.preco_original > o.preco:
        linhas.append(f"❌ De: ~{preco_br(o.preco_original)}~")
        linhas.append(f"✅ Por: *{preco_br(o.preco)}*{selo}")
    elif o.preco:
        linhas.append(f"✅ *{preco_br(o.preco)}*{selo}")

    if o.extra:
        linhas.append(o.extra)

    linhas += ["", _PLATAFORMA.get(o.plataforma, o.plataforma), f"🛒 {o.url}"]
    return "\n".join(linhas)
