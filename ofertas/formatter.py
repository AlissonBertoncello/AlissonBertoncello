"""Texto da mensagem no formato do WhatsApp (*negrito*, ~riscado~)."""
from .models import Grupo, Oferta

_PLATAFORMA = {
    "mercadolivre": "💛 Mercado Livre",
    "shopee": "🧡 Shopee",
}


def preco_br(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def montar_mensagem(o: Oferta, grupo: Grupo | None = None) -> str:
    linhas = [f"🔥 *{o.titulo[:180]}*", ""]

    selo = f"  🔻 *-{o.desconto}%*" if o.desconto else ""
    if o.preco and o.preco_original and o.preco_original > o.preco:
        linhas.append(f"❌ De: ~{preco_br(o.preco_original)}~")
        linhas.append(f"✅ Por: *{preco_br(o.preco)}*{selo}")
        linhas.append(f"💰 Você economiza *{preco_br(o.preco_original - o.preco)}*")
    elif o.preco:
        linhas.append(f"✅ *{preco_br(o.preco)}*{selo}")

    if o.extra:
        linhas.append(o.extra)

    linhas += ["", _PLATAFORMA.get(o.plataforma, o.plataforma), f"🛒 {o.link}"]

    if grupo and grupo.convite:
        linhas += ["", "💬 Envie essa oferta para uma amiga!", f"👉 {grupo.convite}"]
    return "\n".join(linhas)
