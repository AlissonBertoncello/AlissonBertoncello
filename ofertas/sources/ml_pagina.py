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


def _url(cat_id: str, pagina: int) -> str:
    params = []
    if cat_id:
        params.append(f"category={cat_id}")
    if pagina > 1:
        params.append(f"page={pagina}")
    return URL_OFERTAS + ("?" + "&".join(params) if params else "")


def _html_requests(s: requests.Session, url: str) -> str | None:
    """Jeito rápido (sem navegador). None se der erro de rede/HTTP."""
    try:
        r = s.get(url, timeout=30)
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        log.warning("Página de ofertas (acesso direto) %s: %s", url, e)
        return None


def _html_navegador(urls: list[str]) -> dict[str, str]:
    """Abre as páginas no Google Chrome de verdade (o mesmo perfil do link de afiliado),
    como uma pessoa navegando: o ML às vezes responde sem produtos ao acesso direto."""
    from ..afiliado_ml import pagina_chrome

    with pagina_chrome() as page:
        return ler_paginas(page, urls)


def ler_paginas(page, urls: list[str], pausa_s: tuple[float, float] = (0, 0)) -> dict[str, str]:
    """HTML de cada página (já com os cards carregados). Para na primeira que vier bloqueada.
    pausa_s: espera aleatória entre uma página e outra, como uma pessoa navegando."""
    import random

    htmls: dict[str, str] = {}
    for i, url in enumerate(urls):
        if i and pausa_s[1]:
            time.sleep(random.uniform(*pausa_s))
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector("div.poly-card", timeout=15000)
            except Exception:
                pass  # sem cards: o HTML vai para o arquivo de diagnóstico
            htmls[url] = page.content()
        except Exception as e:
            log.warning("Página de ofertas (Chrome) %s: %s", url, e)
            continue
        if e_bloqueio(htmls[url]):
            break
    return htmls


def _titulo(html: str | None) -> str:
    if not html:
        return ""
    t = BeautifulSoup(html, "lxml").title
    return t.get_text(strip=True)[:80] if t else ""


def e_bloqueio(html: str | None) -> bool:
    """O ML barrou a visita: página "Segurança — Mercado Livre" (pede para provar que não é
    robô) ou uma página praticamente vazia (~200 bytes, sem título) no lugar das ofertas."""
    if html is None:
        return False
    if _titulo(html).lower().startswith(("segurança", "seguranca", "security")):
        return True
    return len(html) < 2000 and not _titulo(html) and "poly-card" not in html


def _salvar_debug(url: str, html: str | None) -> None:
    """Guarda a página que veio sem produtos, para descobrir o motivo."""
    from ..config import DATA_DIR
    titulo = _titulo(html)
    try:
        (DATA_DIR / "ml_ofertas_debug.html").write_text(html or "", encoding="utf-8")
    except OSError:
        pass
    log.warning("Página de ofertas sem produtos mesmo pelo Chrome (%s | título: %r | %d bytes) — "
                "cópia salva em data/ml_ofertas_debug.html", url, titulo, len(html or ""))


# No modo "auto", quando o acesso direto vem sem produtos, as próximas buscas vão
# direto ao Chrome (sem perder tempo); de vez em quando o acesso direto é testado de novo.
RETESTAR_DIRETO_A_CADA = 20
_pular_direto = 0

# Quando o ML responde com a verificação de segurança, a página de ofertas fica pausada
# por algumas horas: cada tentativa só gastaria ~16 s e o produto continua vindo pela API.
PAUSA_VERIFICACAO_HORAS = 6
_pausada_ate = 0.0


def pausada() -> bool:
    return time.time() < _pausada_ate


def _pausar_por_verificacao() -> None:
    global _pausada_ate
    _pausada_ate = time.time() + PAUSA_VERIFICACAO_HORAS * 3600
    log.warning("Mercado Livre pediu verificação de segurança na página de ofertas — ela fica "
                "pausada por %d h (os produtos continuam vindo pela API). Para liberar antes: feche "
                "o bot, rode o LOGIN_MERCADOLIVRE.bat, abra mercadolivre.com.br/ofertas nessa "
                "janela e resolva a verificação.", PAUSA_VERIFICACAO_HORAS)


def buscar_ofertas(categorias: dict[str, str], paginas: int = 1, inicio: int = 1,
                   navegador: str = "auto") -> list[Oferta]:
    """Páginas inicio..inicio+paginas-1 de mercadolivre.com.br/ofertas de cada categoria.

    navegador: "auto" = tenta o acesso direto e, se vier sem produtos, abre no Chrome;
    "sempre" = só pelo Chrome; "nunca" = só acesso direto.
    """
    if pausada():
        return []
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
    alvos = [(nome, _url(cat_id, pagina))
             for cat_id, nome in (categorias or {"": "todas"}).items()
             for pagina in range(max(1, inicio), max(1, inicio) + max(1, paginas))]

    global _pular_direto
    achadas_por_url: dict[str, list[Oferta]] = {}
    direto = navegador == "nunca" or (navegador == "auto" and _pular_direto <= 0)
    if navegador == "auto" and _pular_direto > 0:
        _pular_direto -= 1
    if direto:
        for _, url in alvos:
            html = _html_requests(s, url)
            achadas_por_url[url] = parse_pagina(html) if html else []
            time.sleep(1)
        if navegador == "auto" and not any(achadas_por_url.values()):
            _pular_direto = RETESTAR_DIRETO_A_CADA
            log.info("Página de ofertas: acesso direto veio sem produtos — "
                     "as próximas %d buscas vão direto pelo Chrome", RETESTAR_DIRETO_A_CADA)

    faltando = [url for _, url in alvos if not achadas_por_url.get(url)]
    if faltando and navegador != "nunca":
        try:
            htmls = _html_navegador(faltando)
        except Exception as e:
            log.error("Página de ofertas: não consegui abrir o Chrome: %s", e)
            htmls = {}
        for url in faltando:
            achadas_por_url[url] = parse_pagina(htmls[url]) if htmls.get(url) else []
            if achadas_por_url[url]:
                continue
            if e_bloqueio(htmls.get(url)):
                if not pausada():
                    _pausar_por_verificacao()
            else:
                _salvar_debug(url, htmls.get(url))

    ofertas: dict[str, Oferta] = {}
    for nome, url in alvos:
        achadas = achadas_por_url.get(url) or []
        for o in achadas:
            ofertas.setdefault(o.id_produto, o)
        log.info("Página de ofertas %s: %d ofertas", nome, len(achadas))
    return list(ofertas.values())
