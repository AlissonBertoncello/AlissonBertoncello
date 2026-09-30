"""Cliente da Evolution API (WhatsApp via Docker, gratuita e local).

A Evolution roda no Docker Desktop (evolution/docker-compose.yml). Este módulo
sobe os containers se precisar, faz o login por QR Code e envia mensagens.
Endpoints da v2: /instance/*, /group/fetchAllGroups, /message/sendMedia|sendText.
"""
import base64
import logging
import os
import secrets
import subprocess
import time

import requests

from .config import BASE_DIR, DATA_DIR, config

log = logging.getLogger("ofertas.whatsapp")

COMPOSE = BASE_DIR / "evolution" / "docker-compose.yml"
ARQ_QR = DATA_DIR / "whatsapp_qr.html"   # página que o navegador recarrega sozinha


class ErroWhatsApp(RuntimeError):
    pass


def garantir_api_key() -> str:
    """Gera a EVOLUTION_API_KEY na primeira vez e grava no .env (é uma senha local)."""
    if config.evolution_api_key:
        return config.evolution_api_key
    chave = secrets.token_hex(16)
    env = BASE_DIR / ".env"
    with open(env, "a", encoding="utf-8") as f:
        f.write(f"\n# Gerada automaticamente: senha da Evolution API local\nEVOLUTION_API_KEY={chave}\n")
    config.evolution_api_key = chave
    print("🔑 EVOLUTION_API_KEY gerada e salva no .env")
    return chave


class Evolution:
    def __init__(self, url: str = "", api_key: str = "", instancia: str = "",
                 sessao: requests.Session | None = None):
        self.url = (url or config.evolution_url).rstrip("/")
        self.instancia = instancia or config.evolution_instancia
        self.s = sessao or requests.Session()
        self.s.headers.update({"apikey": api_key or garantir_api_key(),
                               "Content-Type": "application/json"})
        self._grupos: dict[str, str] = {}   # nome (minúsculo) -> id do grupo (@g.us)

    # ── infraestrutura ──────────────────────────────────────────────
    def no_ar(self) -> bool:
        try:
            return self.s.get(self.url + "/", timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def subir(self, espera_s: int = 120) -> None:
        """Garante a Evolution no ar: se não responder, roda docker compose up -d."""
        if self.no_ar():
            return
        print("🐳 Iniciando a Evolution API no Docker (a 1ª vez baixa ~1 GB e demora)...")
        env = {**os.environ, "EVOLUTION_API_KEY": garantir_api_key()}
        try:
            r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "up", "-d"], env=env)
        except FileNotFoundError:
            raise ErroWhatsApp("Docker não encontrado — instale o Docker Desktop "
                               "(https://www.docker.com/products/docker-desktop/) e abra-o.")
        if r.returncode != 0:
            raise ErroWhatsApp("docker compose falhou — o Docker Desktop está aberto?")
        fim = time.time() + espera_s
        while time.time() < fim:
            if self.no_ar():
                log.info("Evolution API no ar em %s", self.url)
                return
            time.sleep(3)
        raise ErroWhatsApp(f"A Evolution API não respondeu em {self.url} após {espera_s}s")

    def _req(self, metodo: str, caminho: str, **kw) -> dict | list:
        try:
            r = self.s.request(metodo, self.url + caminho, timeout=60, **kw)
        except requests.RequestException as e:
            raise ErroWhatsApp(f"Evolution API fora do ar ({self.url}): {e}")
        if r.status_code >= 400:
            raise ErroWhatsApp(f"{metodo} {caminho} respondeu HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # ── conexão ─────────────────────────────────────────────────────
    def estado(self) -> str:
        """"open" = conectado; "close"/"connecting" = precisa ler o QR."""
        try:
            d = self._req("GET", f"/instance/connectionState/{self.instancia}")
        except ErroWhatsApp as e:
            if "HTTP 404" in str(e):
                return "inexistente"
            raise
        return ((d.get("instance") or {}).get("state")) or "desconhecido"

    def aguardar_conexao(self, espera_s: float = 40, intervalo_s: float = 2) -> str:
        """Espera o número reconectar sozinho (logo depois de o Docker/Evolution
        iniciar o estado passa alguns segundos em "connecting"). Devolve o último estado."""
        fim = time.time() + espera_s
        estado = self.estado()
        while estado != "open" and estado != "inexistente" and time.time() < fim:
            time.sleep(intervalo_s)
            estado = self.estado()
        return estado

    def qr_code(self) -> str | None:
        """Cria a instância se não existir e devolve o QR Code (imagem base64)."""
        if self.estado() == "inexistente":
            d = self._req("POST", "/instance/create", json={
                "instanceName": self.instancia, "qrcode": True, "integration": "WHATSAPP-BAILEYS"})
            qr = (d.get("qrcode") or {}).get("base64")
            if qr:
                return qr
        d = self._req("GET", f"/instance/connect/{self.instancia}")
        return d.get("base64")

    # ── grupos e envio ──────────────────────────────────────────────
    def grupos(self) -> dict[str, str]:
        """{nome do grupo: id} dos grupos em que o número do bot participa."""
        lista = self._req("GET", f"/group/fetchAllGroups/{self.instancia}",
                          params={"getParticipants": "false"})
        return {g.get("subject") or g["id"]: g["id"] for g in lista if g.get("id")}

    def id_do_grupo(self, nome_ou_id: str) -> str:
        """Aceita o id (…@g.us) ou o nome exato do grupo (maiúsculas/minúsculas tanto faz)."""
        if nome_ou_id.endswith("@g.us"):
            return nome_ou_id
        chave = nome_ou_id.strip().lower()
        if chave not in self._grupos:
            self._grupos = {n.strip().lower(): i for n, i in self.grupos().items()}
        if chave not in self._grupos:
            raise ErroWhatsApp(f"Grupo '{nome_ou_id}' não encontrado no WhatsApp do bot "
                               "(veja os nomes com: uv run python -m ofertas whatsapp-grupos)")
        return self._grupos[chave]

    def enviar_foto(self, destino: str, imagem_url: str, legenda: str) -> None:
        self._req("POST", f"/message/sendMedia/{self.instancia}", json={
            "number": destino, "mediatype": "image", "mimetype": "image/jpeg",
            "media": imagem_url, "fileName": "oferta.jpg", "caption": legenda, "delay": 1200})

    def enviar_texto(self, destino: str, texto: str) -> None:
        self._req("POST", f"/message/sendText/{self.instancia}", json={
            "number": destino, "text": texto, "linkPreview": True, "delay": 1200})


_PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{recarregar}"><title>WhatsApp do bot</title>
<style>body{{font-family:sans-serif;text-align:center;padding:24px;background:#f4f4f4}}
img{{width:320px;height:320px;background:#fff;padding:12px;border-radius:8px}}</style></head>
<body><h2>{titulo}</h2>{corpo}</body></html>"""


def salvar_qr(qr_base64: str | None = None, conectado: bool = False, abrir: bool = False) -> bool:
    """Grava a página data/whatsapp_qr.html (o navegador recarrega sozinho a cada 3s,
    então sempre mostra o QR mais recente). Uma página no navegador não fica travada
    pelo Windows, ao contrário de uma imagem aberta no visualizador de fotos."""
    if conectado:
        html = _PAGINA.format(recarregar=3600, titulo="✅ WhatsApp conectado!",
                              corpo="<p>Pode fechar esta página.</p>")
    else:
        dados = (qr_base64 or "").split(",", 1)[-1]
        base64.b64decode(dados, validate=True)  # garante que é uma imagem válida
        html = _PAGINA.format(
            recarregar=3, titulo="Leia o QR Code com o celular do número do bot",
            corpo=f'<img src="data:image/png;base64,{dados}" alt="QR Code">'
                  "<p>WhatsApp › Aparelhos conectados › Conectar um aparelho</p>"
                  "<p><small>O código se renova sozinho — não precisa recarregar.</small></p>")
    temp = ARQ_QR.with_suffix(".tmp")
    try:
        temp.write_text(html, encoding="utf-8")
        os.replace(temp, ARQ_QR)
    except OSError as e:
        log.warning("Não consegui gravar o QR Code em %s: %s", ARQ_QR, e)
        return False
    if abrir:
        try:
            import webbrowser
            webbrowser.open(ARQ_QR.as_uri())
        except Exception:
            pass
    return True


def whatsapp_login(espera_s: int = 180) -> None:
    """Sobe a Evolution, mostra o QR Code e espera o celular do bot conectar."""
    evo = Evolution()
    evo.subir()
    print("⏳ Verificando a conexão do WhatsApp do bot...")
    if evo.aguardar_conexao(30) == "open":
        print("✅ O WhatsApp do bot já está conectado.")
        return
    print("\n➡️  No celular do NÚMERO DO BOT: WhatsApp > Aparelhos conectados > Conectar um aparelho")
    print(f"    e leia o QR Code que vai abrir no navegador (página: {ARQ_QR}).\n")
    fim = time.time() + espera_s
    proximo_qr = 0.0
    recebeu_qr = False
    while time.time() < fim:
        if time.time() >= proximo_qr:
            qr = evo.qr_code()
            if qr and salvar_qr(qr, abrir=not recebeu_qr):  # abre o navegador só na 1ª vez
                recebeu_qr = True
            # o QR do WhatsApp vence em ~30-40s; enquanto não chega o 1º, tenta de novo logo
            proximo_qr = time.time() + (30 if qr else 5)
        time.sleep(3)
        if evo.estado() == "open":
            salvar_qr(conectado=True)
            print("✅ WhatsApp conectado! A sessão fica salva no Docker.")
            return
    if not recebeu_qr:
        raise ErroWhatsApp("A Evolution API não conseguiu gerar o QR Code — ela não está "
                           "alcançando o WhatsApp. Confira a internet/antivírus e tente de novo.")
    raise ErroWhatsApp("Tempo esgotado sem ler o QR Code — rode o login de novo.")
