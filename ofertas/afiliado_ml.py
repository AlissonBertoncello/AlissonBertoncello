"""Link de afiliado do Mercado Livre via Linkbuilder.

O ML não tem API pública para afiliados, mas o Linkbuilder do painel usa uma API
interna simples (createLink), autenticada pelos cookies da sessão. O bot chama
essa API de dentro de uma página logada (perfil persistente do Chrome em
data/ml_profile). Faça login uma única vez com:

    uv run python -m ofertas ml-login
"""
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .config import DATA_DIR, config
from .models import Oferta

log = logging.getLogger("ofertas.afiliado")

URL_LINKBUILDER = "https://www.mercadolivre.com.br/afiliados/linkbuilder"
API_CREATELINK = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
PERFIL_DIR = DATA_DIR / "ml_profile"
TAMANHO_LOTE = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

_RE_ID = re.compile(r"(MLB)-?(\d{6,})", re.I)


class ErroAfiliado(RuntimeError):
    pass


def e_link_ml(url: str) -> bool:
    return any(d in url for d in ("mercadolivre.com", "mercadolibre.com", "meli.la/"))


def extrair_id(url: str) -> str | None:
    """"https://.../MLB-123456789-fone" -> "MLB123456789"."""
    m = _RE_ID.search(url)
    return (m.group(1).upper() + m.group(2)) if m else None


def tem_sessao() -> bool:
    return PERFIL_DIR.exists() and any(PERFIL_DIR.iterdir())


# ── Login (uma vez) ──────────────────────────────────────────────────

def _achar_chrome() -> str:
    """Caminho do Google Chrome instalado (Windows, macOS ou Linux)."""
    candidatos: list[str] = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    chave = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
                    with winreg.OpenKey(hive, chave) as k:
                        candidatos.append(winreg.QueryValueEx(k, None)[0])
                except OSError:
                    continue
        except ImportError:
            pass
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidatos.append(str(Path(base) / "Google/Chrome/Application/chrome.exe"))
    elif sys.platform == "darwin":
        candidatos += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:
        for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            achado = shutil.which(nome)
            if achado:
                candidatos.append(achado)
    for c in candidatos:
        if c and Path(c).exists():
            return c
    raise ErroAfiliado("Google Chrome não encontrado — instale o Google Chrome e tente de novo.")


def ml_login() -> None:
    """Abre um Chrome comum (sem automação) no perfil do bot para você logar no ML uma vez."""
    chrome = _achar_chrome()
    PERFIL_DIR.mkdir(parents=True, exist_ok=True)
    print("\n➡️  Vai abrir um Chrome normal com o perfil do bot (separado do seu).")
    print("    1. Faça login no Mercado Livre (senha, 2FA etc.)")
    print("    2. Confira que o Linkbuilder carrega logado")
    print("    3. FECHE o navegador para terminar\n")
    proc = subprocess.Popen([chrome, f"--user-data-dir={PERFIL_DIR}", "--no-first-run",
                             "--no-default-browser-check", URL_LINKBUILDER])
    proc.wait()
    print(f"✅ Perfil salvo em {PERFIL_DIR} — o bot usa essa sessão sozinho daqui pra frente.")
    print('   Teste com: uv run python -m ofertas converter "<link de produto do ML>"')


# ── Geração dos links (Playwright + sessão logada) ───────────────────

def _abrir_contexto(pw):
    """Google Chrome instalado + perfil persistente do projeto, headless.

    O ML recusa o "Chrome for Testing" do Playwright, então usamos o Chrome real
    (channel="chrome") e removemos as marcas de automação.
    """
    kwargs = dict(
        channel="chrome",
        headless=True,
        locale="pt-BR",
        user_agent=USER_AGENT,  # o headless se anuncia como HeadlessChrome
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    try:
        return pw.chromium.launch_persistent_context(str(PERFIL_DIR), **kwargs)
    except Exception as e:
        if "chrome" not in str(e).lower():
            raise
        log.warning("Google Chrome não encontrado (%s); usando o Chromium do projeto", type(e).__name__)
        kwargs.pop("channel")
        return pw.chromium.launch_persistent_context(str(PERFIL_DIR), **kwargs)


def criar_links(page, urls: list[str], etiqueta: str) -> list[str]:
    """Chama a API interna do Linkbuilder de dentro da página logada; retorna os short links.

    POST createLink {"urls": [...], "tag": "<etiqueta>"} ->
    {"urls": [{"short_url": "https://meli.la/...", ...}, ...]}
    """
    r = page.evaluate(
        """async ({api, urls, tag}) => {
            const resp = await fetch(api, {
                method: 'POST',
                headers: {'content-type': 'application/json'},
                body: JSON.stringify({urls, tag}),
            });
            const corpo = await resp.text();
            try { return {http: resp.status, dados: JSON.parse(corpo)}; }
            catch (e) { return {http: resp.status, texto: corpo.slice(0, 300)}; }
        }""",
        {"api": API_CREATELINK, "urls": urls, "tag": etiqueta},
    )
    if r.get("http") in (401, 403):
        raise ErroAfiliado("Sessão do ML expirou — rode de novo: uv run python -m ofertas ml-login")
    if r.get("http") != 200 or not r.get("dados"):
        raise ErroAfiliado(f"createLink respondeu HTTP {r.get('http')}: {r.get('texto', '')}")
    itens = r["dados"].get("urls") or []
    links = [i.get("short_url") or "" for i in itens]
    if len(links) != len(urls) or not all(links):
        raise ErroAfiliado(f"createLink devolveu {sum(1 for l in links if l)} links "
                           f"para {len(urls)} URLs: {r['dados']}")
    return links


def gerar_links_afiliado(ofertas: list[Oferta]) -> int:
    """Preenche oferta.url_afiliado via Linkbuilder (lotes de 10). Retorna quantos gerou."""
    pendentes = [o for o in ofertas if not o.url_afiliado and o.url_produto]
    if not pendentes:
        return 0
    if not config.ml_etiqueta:
        raise ErroAfiliado("ML_ETIQUETA não configurada no .env "
                           "(é a 'Etiqueta em uso' do Linkbuilder no painel de afiliados)")
    if not tem_sessao():
        raise ErroAfiliado("Sessão do ML não encontrada — rode: uv run python -m ofertas ml-login")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = _abrir_contexto(pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL_LINKBUILDER, wait_until="domcontentloaded")
            if "login" in page.url or "registration" in page.url:
                raise ErroAfiliado("Sessão do ML expirou — rode de novo: "
                                   "uv run python -m ofertas ml-login")
            page.wait_for_timeout(1500)  # deixa os scripts de sessão da página rodarem
            for i in range(0, len(pendentes), TAMANHO_LOTE):
                lote = pendentes[i:i + TAMANHO_LOTE]
                links = criar_links(page, [o.url_produto for o in lote], config.ml_etiqueta)
                for o, link in zip(lote, links):
                    o.url_afiliado = link
        finally:
            ctx.close()
    log.info("Mercado Livre: %d links de afiliado gerados", len(pendentes))
    return len(pendentes)
