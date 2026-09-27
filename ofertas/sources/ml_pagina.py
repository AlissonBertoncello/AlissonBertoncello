"""Plano B: lê a página pública de ofertas do ML (mercadolivre.com.br/ofertas).

Usado quando a API não devolve resultados (ex: busca bloqueada com 403).
Mesmo método do bot do Telegram; se o ML mudar o layout, os seletores ficam aqui.
"""
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from ..models import Oferta

log = logging.getLogger("ofertas.ml")

URL_OFERTAS = "https://www.mercadolivre.com.br/ofertas"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
_RE_ID = re.compile(r"(MLB-?\d{6,})")


def parse_preco_br(texto: str | None) -> float | None:
    """Converte "1.234,56" / "1.234" / "56,43" em float."""
    t = re.sub(r"[^\d,.]", "", texto or "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.rsplit(".", 1)[1]) == 3):
        t = t.replace(".", "")  # ponto de milhar, sem centavos
    try:
        return float(t)
    except ValueError:
        return None


def _preco_de(card, seletor_base: str) -> float | None:
    fracao = card.select_one(f"{seletor_base} .andes-money-amount__fraction")
    if not fracao:
        return None
    centavos = card.select_one(f"{seletor_base} .andes-money-amount__cents")
    texto = fracao.get_text(strip=True) + ("," + centavos.get_text(strip=True) if centavos else "")
    return parse_preco_br(texto)


def _parse_card(card) -> Oferta | None:
    a = card.select_one("a.poly-component__title")
    if not (a and a.get("href")):
        return None
    url = a["href"].split("#")[0].split("?")[0]
    m = _RE_ID.search(a["href"])
    id_produto = m.group(1).replace("-", "") if m else url.rstrip("/").rsplit("/", 1)[-1][:40]

    desconto = None
    selo = card.select_one(".poly-price__discount-polylabel, .andes-money-amount__discount")
    if selo:
        m = re.search(r"(\d+)\s*%", selo.get_text())
        desconto = int(m.group(1)) if m else None

    img = card.select_one("img.poly-component__picture")
    imagem = (img.get("data-src") or img.get("src")) if img else None
    if imagem and imagem.startswith("data:"):
        imagem = None  # placeholder de lazy-load

    partes = []
    if "Frete grátis" in card.get_text():
        partes.append("🚚 Frete grátis")
    pix = card.select_one(".poly-price__unit-description")
    if pix and "pix" in pix.get_text().lower():
        partes.append("💠 preço no Pix")

    return Oferta(
        plataforma="mercadolivre",
        id_produto=id_produto,
        titulo=a.get_text(strip=True),
        url_produto=url,
        preco=_preco_de(card, ".poly-price__current"),
        preco_original=_preco_de(card, "s.andes-money-amount--previous"),
        desconto_pct=desconto,
        imagem=imagem,
        extra=" · ".join(partes) or None,
    )


def parse_pagina(html: str) -> list[Oferta]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.poly-card")
    ofertas = [o for o in (_parse_card(c) for c in cards) if o]
    if cards and not ofertas:
        log.warning("Página de ofertas do ML mudou de layout? %d cards, 0 lidos", len(cards))
    return ofertas


def buscar_ofertas(categorias: dict[str, str], paginas: int = 1, inicio: int = 1) -> list[Oferta]:
    """Páginas inicio..inicio+paginas-1 de mercadolivre.com.br/ofertas de cada categoria."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
    ofertas: dict[str, Oferta] = {}
    for cat_id, nome in (categorias or {"": "todas"}).items():
        for pagina in range(max(1, inicio), max(1, inicio) + max(1, paginas)):
            params = {}
            if cat_id:
                params["category"] = cat_id
            if pagina > 1:
                params["page"] = pagina
            try:
                r = s.get(URL_OFERTAS, params=params or None, timeout=30)
                r.raise_for_status()
            except requests.RequestException as e:
                log.error("Página de ofertas %s: %s", nome, e)
                break
            achadas = parse_pagina(r.text)
            for o in achadas:
                ofertas.setdefault(o.id_produto, o)
            log.info("Página de ofertas %s: %d ofertas", nome, len(achadas))
            time.sleep(1)
    return list(ofertas.values())
