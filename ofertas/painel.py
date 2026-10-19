"""Painel de configuração local: abre no navegador e edita o config.yaml e o .env.

    uv run python -m ofertas painel        (ou CONFIGURAR.bat)

Só escuta em 127.0.0.1 (o próprio notebook). Ao salvar, os comentários do
config.yaml são mantidos e uma cópia do arquivo anterior fica em data/.
O bot em execução aplica as mudanças sozinho em até ~10 segundos.
"""
import json
import logging
import re
import shutil
import socket
import sqlite3
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .config import BASE_DIR, DATA_DIR

log = logging.getLogger("ofertas.painel")

PORTA = 8765
ARQ_CONFIG = BASE_DIR / "config.yaml"
ARQ_ENV = BASE_DIR / ".env"
ARQ_HTML = Path(__file__).with_name("painel.html")

# campos do .env que o painel mostra; os "secretos" nunca voltam para a tela
CAMPOS_ENV = {
    "ML_CLIENT_ID": False,
    "ML_CLIENT_SECRET": True,
    "ML_ETIQUETA": False,
    "SHOPEE_APP_ID": False,
    "SHOPEE_APP_SECRET": True,
}
_RE_CHAVE = re.compile(r"^[a-z0-9_]{1,30}$")
_RE_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_RE_CAT = re.compile(r"^MLB\d{1,10}$")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _carregar() -> CommentedMap:
    if not ARQ_CONFIG.exists():
        return CommentedMap()
    with open(ARQ_CONFIG, encoding="utf-8") as f:
        return _yaml().load(f) or CommentedMap()


# ── .env ─────────────────────────────────────────────────────────────

def ler_env(caminho: Path | None = None) -> dict[str, str]:
    caminho = caminho or ARQ_ENV
    valores = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", linha)
            if m:
                valores[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return valores


def gravar_env(novos: dict[str, str], caminho: Path | None = None) -> None:
    """Troca só as chaves pedidas, mantendo o resto do arquivo (comentários e outras chaves)."""
    caminho = caminho or ARQ_ENV
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    faltam = dict(novos)
    for i, linha in enumerate(linhas):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", linha)
        if m and m.group(1) in faltam:
            linhas[i] = f"{m.group(1)}={faltam.pop(m.group(1))}"
    linhas += [f"{k}={v}" for k, v in faltam.items()]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


# ── config.yaml -> tela ──────────────────────────────────────────────

def _lista(valor) -> list[str]:
    itens = valor if isinstance(valor, list) else [valor]
    return [str(v).strip() for v in itens if v is not None and str(v).strip()]


def ler_tudo() -> dict:
    y = _carregar()
    geral = y.get("geral") or {}
    filtros = y.get("filtros") or {}
    fontes = y.get("fontes") or {}
    grupos = []
    for chave, g in (y.get("grupos") or {}).items():
        g = g or {}
        cats = g.get("categorias") or {}
        if not isinstance(cats, dict):
            from .categorias import nome
            cats = {str(c): nome(str(c)) for c in cats}
        convite = str(g.get("convite") or "")
        grupos.append({
            "chave": str(chave),
            "ativo": g.get("ativo") is not False,
            "nome": str(g.get("nome") or chave),
            "whatsapp": _lista(g.get("whatsapp")),
            "convite": convite if convite.startswith("http") else "",
            "categorias": [{"id": str(k), "nome": str(v)} for k, v in cats.items()],
            "shopee": _lista(g.get("shopee")),
            "bloquear": _lista(g.get("bloquear")),
            "ganchos": _lista(g.get("ganchos")),
            "chamada": str(g.get("chamada") or ""),
            "chamada_compra": str(g.get("chamada_compra") or ""),
            "peso_ml": _peso(g, "mercadolivre"),
            "peso_shopee": _peso(g, "shopee"),
        })
    env = ler_env()
    return {
        "geral": {
            "intervalo_minutos": int(geral.get("intervalo_minutos", 30)),
            "max_posts_por_ciclo": int(geral.get("max_posts_por_ciclo", 1)),
            "espacamento_segundos": int(geral.get("espacamento_segundos", 15)),
            "nao_repetir_dias": int(geral.get("nao_repetir_dias", 7)),
            "horario_ativo": str(geral.get("horario_ativo") or ""),
        },
        "filtros": {
            "desconto_minimo": int(filtros.get("desconto_minimo", 0) or 0),
            "preco_minimo": float(filtros.get("preco_minimo", 0) or 0),
            "preco_maximo": float(filtros.get("preco_maximo", 0) or 0),
            "palavras_bloqueadas": _lista(filtros.get("palavras_bloqueadas")),
        },
        "fontes": {
            "mercadolivre": bool((fontes.get("mercadolivre") or {}).get("ativa", True)),
            "shopee": bool((fontes.get("shopee") or {}).get("ativa", False)),
        },
        "destino": str(y.get("destino") or "console"),
        "grupos": grupos,
        "env": {k: {"secreto": s, "definido": bool(env.get(k)), "valor": "" if s else env.get(k, "")}
                for k, s in CAMPOS_ENV.items()},
    }


def _peso(g: dict, loja: str) -> int:
    try:
        return max(0, int((g.get("proporcao") or {}).get(loja, 1)))
    except (TypeError, ValueError, AttributeError):
        return 1


# ── tela -> config.yaml ──────────────────────────────────────────────

def validar(d: dict) -> list[str]:
    erros = []
    g = d.get("geral") or {}
    for campo, minimo in (("intervalo_minutos", 1), ("max_posts_por_ciclo", 1),
                          ("espacamento_segundos", 0), ("nao_repetir_dias", 0)):
        v = g.get(campo)
        if not isinstance(v, int) or isinstance(v, bool) or v < minimo:
            erros.append(f"Geral: '{campo}' precisa ser um número inteiro a partir de {minimo}")
    h = str(g.get("horario_ativo") or "")
    if h and not (len(h.split("-")) == 2 and all(_RE_HORA.match(p) for p in h.split("-"))):
        erros.append("Geral: horário ativo inválido (use 08:00-23:00, ou deixe 24h)")
    f = d.get("filtros") or {}
    if not isinstance(f.get("desconto_minimo"), int) or not 0 <= f["desconto_minimo"] <= 99:
        erros.append("Filtros: desconto mínimo precisa ser de 0 a 99")
    for campo in ("preco_minimo", "preco_maximo"):
        if not isinstance(f.get(campo), (int, float)) or f[campo] < 0:
            erros.append(f"Filtros: '{campo}' precisa ser 0 ou mais")
    if d.get("destino") not in ("console", "whatsapp"):
        erros.append("Destino precisa ser 'console' ou 'whatsapp'")

    chaves = set()
    for i, gr in enumerate(d.get("grupos") or [], 1):
        nome = gr.get("nome") or f"grupo {i}"
        chave = gr.get("chave") or ""
        if not _RE_CHAVE.match(chave):
            erros.append(f"{nome}: o código interno precisa ter só letras minúsculas, números ou _")
        elif chave in chaves:
            erros.append(f"{nome}: código interno '{chave}' repetido")
        chaves.add(chave)
        if not gr.get("nome", "").strip():
            erros.append(f"Grupo {i}: falta o nome")
        for c in gr.get("categorias") or []:
            if not _RE_CAT.match(str(c.get("id", ""))):
                erros.append(f"{nome}: categoria '{c.get('id')}' inválida (formato MLB123)")
        if gr.get("ativo"):
            if not (gr.get("categorias") or gr.get("shopee")):
                erros.append(f"{nome}: grupo ativo precisa de pelo menos uma categoria ou palavra da Shopee")
            if d.get("destino") == "whatsapp" and not gr.get("whatsapp"):
                erros.append(f"{nome}: grupo ativo precisa do nome do grupo no WhatsApp")
        conv = (gr.get("convite") or "").strip()
        if conv and not conv.startswith(("https://", "http://")):
            erros.append(f"{nome}: o convite precisa ser um link (https://...)")
        pesos = [gr.get("peso_ml", 1), gr.get("peso_shopee", 1)]
        if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10 for v in pesos):
            erros.append(f"{nome}: a proporção das lojas precisa ser de 0 a 10")
        elif gr.get("ativo") and sum(pesos) == 0:
            erros.append(f"{nome}: a proporção das lojas não pode ser 0 nas duas")
        if any("\n" in str(x) for x in [gr.get("chamada", ""), gr.get("chamada_compra", ""),
                                          *(gr.get("ganchos") or [])]):
            erros.append(f"{nome}: ganchos e chamadas precisam ter uma linha cada")
    if not any(gr.get("ativo") for gr in d.get("grupos") or []):
        erros.append("Deixe pelo menos um grupo ativo")
    for k, v in (d.get("env") or {}).items():
        if k not in CAMPOS_ENV:
            erros.append(f"Credencial desconhecida: {k}")
        elif not isinstance(v, str) or any(c in v for c in "\r\n"):
            erros.append(f"{k}: valor inválido")
    return erros


def _flow(itens: list[str]) -> CommentedSeq:
    s = CommentedSeq(itens)
    s.fa.set_flow_style()
    return s


def _bloco(itens: list[str]) -> CommentedSeq:
    return CommentedSeq(itens)


def _set(mapa: CommentedMap, chave: str, valor) -> None:
    """Grava só se mudou (assim listas sem mudança mantêm os comentários de seção)."""
    atual = mapa.get(chave)
    if isinstance(atual, list) and isinstance(valor, list) and [str(x) for x in atual] == valor:
        return
    if isinstance(atual, dict) and isinstance(valor, dict) and \
            {str(k): str(v) for k, v in atual.items()} == valor:
        return
    if atual == valor and isinstance(atual, str) == isinstance(valor, str) \
            and isinstance(atual, bool) == isinstance(valor, bool):
        return
    if isinstance(valor, dict):
        valor = CommentedMap(valor)
    mapa[chave] = valor


def _aplicar_grupo(m: CommentedMap, gr: dict) -> None:
    if gr["ativo"]:
        if "ativo" in m:
            del m["ativo"]
    else:
        if "ativo" in m:
            m["ativo"] = False
        else:
            m.insert(0, "ativo", False)
    _set(m, "nome", gr["nome"].strip())
    _set(m, "categorias", {c["id"]: c["nome"].strip() or c["id"] for c in gr.get("categorias") or []})
    wa = [w.strip() for w in gr.get("whatsapp") or [] if w.strip()]
    if wa != _lista(m.get("whatsapp")):
        m["whatsapp"] = wa[0] if len(wa) == 1 else _bloco(wa)
    conv = (gr.get("convite") or "").strip()
    atual = str(m.get("convite") or "")
    if conv or atual.startswith("http"):  # vazio + lembrete entre colchetes: deixa o lembrete
        _set(m, "convite", conv or "[link de convite do grupo]")
    bl = [b.strip() for b in gr.get("bloquear") or [] if b.strip()]
    if bl or "bloquear" in m:
        if bl != _lista(m.get("bloquear")):
            m["bloquear"] = _flow(bl)
    ga = [t.strip() for t in gr.get("ganchos") or [] if t.strip()]
    if ga != _lista(m.get("ganchos")):
        if ga:
            m["ganchos"] = _bloco(ga)
        elif "ganchos" in m:
            del m["ganchos"]
    for campo in ("chamada", "chamada_compra"):
        texto = (gr.get(campo) or "").strip()
        if texto or campo in m:
            _set(m, campo, texto)
    pesos = {"mercadolivre": int(gr.get("peso_ml", 1)), "shopee": int(gr.get("peso_shopee", 1))}
    if pesos != {"mercadolivre": 1, "shopee": 1} or "proporcao" in m:
        _set(m, "proporcao", pesos)
    sh = [t.strip() for t in gr.get("shopee") or [] if t.strip()]
    if sh != _lista(m.get("shopee")):
        m["shopee"] = _bloco(sh)


def aplicar(y: CommentedMap, d: dict) -> CommentedMap:
    """Copia os valores da tela para o YAML carregado (mantendo comentários e a ordem)."""
    geral = y.setdefault("geral", CommentedMap())
    for k, v in d["geral"].items():
        _set(geral, k, v)
    filtros = y.setdefault("filtros", CommentedMap())
    for k in ("desconto_minimo", "preco_minimo", "preco_maximo"):
        v = d["filtros"][k]
        _set(filtros, k, int(v) if float(v).is_integer() else float(v))
    pal = [p.strip() for p in d["filtros"]["palavras_bloqueadas"] if p.strip()]
    if pal != _lista(filtros.get("palavras_bloqueadas")):
        filtros["palavras_bloqueadas"] = _flow(pal)
    fontes = y.setdefault("fontes", CommentedMap())
    for loja in ("mercadolivre", "shopee"):
        _set(fontes.setdefault(loja, CommentedMap()), "ativa", bool(d["fontes"][loja]))
    _set(y, "destino", d["destino"])

    grupos = y.setdefault("grupos", CommentedMap())
    pedidos = {gr["chave"]: gr for gr in d["grupos"]}
    for chave in [k for k in grupos if k not in pedidos]:
        del grupos[chave]
    for chave, gr in pedidos.items():
        if not isinstance(grupos.get(chave), CommentedMap):
            grupos[chave] = CommentedMap()
        _aplicar_grupo(grupos[chave], gr)
    return y


def salvar(d: dict) -> list[str]:
    """Valida e grava config.yaml (+ .env). Retorna a lista de erros (vazia = salvou)."""
    erros = validar(d)
    if erros:
        return erros
    y = aplicar(_carregar(), d)
    texto = StringIO()
    _yaml().dump(y, texto)
    # confere que o arquivo novo é lido pelo bot antes de trocar o antigo
    import yaml as pyyaml
    from .config import ler_grupos
    ler_grupos(pyyaml.safe_load(texto.getvalue()).get("grupos") or {})
    if ARQ_CONFIG.exists():
        shutil.copy2(ARQ_CONFIG, DATA_DIR / "config_anterior.yaml")
    tmp = ARQ_CONFIG.with_suffix(".yaml.tmp")
    tmp.write_text(texto.getvalue(), encoding="utf-8")
    tmp.replace(ARQ_CONFIG)
    # cópia fora do ZIP do projeto: sobrevive às atualizações (GUIA, passo 10)
    shutil.copy2(ARQ_CONFIG, DATA_DIR / "meu_config.yaml")
    novos = {k: v.strip() for k, v in (d.get("env") or {}).items() if v.strip()}
    if novos:
        if ARQ_ENV.exists():
            shutil.copy2(ARQ_ENV, DATA_DIR / "env_anterior.txt")
        gravar_env(novos)
    return []


# ── informações extras para a tela ───────────────────────────────────

def bot_rodando() -> bool:
    from .main import PORTA_TRAVA
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORTA_TRAVA))
        return False
    except OSError:
        return True
    finally:
        s.close()


def status() -> dict:
    envios = []
    banco = DATA_DIR / "ofertas.db"
    if banco.exists():
        with sqlite3.connect(banco) as c:
            try:
                envios = [dict(zip(("grupo", "plataforma", "titulo", "preco", "em"), r)) for r in c.execute(
                    "SELECT grupo, plataforma, titulo, preco, enviada_em FROM envios "
                    "ORDER BY enviada_em DESC LIMIT 15")]
                hoje = dict(c.execute("SELECT grupo, COUNT(*) FROM envios "
                                      "WHERE enviada_em >= date('now', 'localtime') GROUP BY grupo"))
            except sqlite3.Error:
                hoje = {}
    else:
        hoje = {}
    return {"rodando": bot_rodando(), "envios": envios, "hoje": hoje}


_cache_categorias: dict[str, dict] = {}
_trava_ml = threading.Lock()  # uma consulta ao ML por vez (o cliente não é usado em paralelo)


def categorias(cid: str, tentativas: int = 3) -> dict:
    """Categorias principais (cid vazio) ou a categoria cid com as subcategorias.
    Guarda o que já foi aberto e tenta de novo se o Mercado Livre falhar."""
    cid = cid.strip().upper()
    if cid in _cache_categorias:
        return _cache_categorias[cid]
    for n in range(1, tentativas + 1):
        try:
            with _trava_ml:
                dados = _buscar_categorias(cid)
            _cache_categorias[cid] = dados
            return dados
        except Exception as e:
            log.warning("Painel: categorias %s, tentativa %d/%d: %s", cid or "principais", n, tentativas, e)
            if n == tentativas:
                raise
            time.sleep(1.5 * n)


def _buscar_categorias(cid: str) -> dict:
    from .sources.mercadolivre import cliente_padrao
    c = cliente_padrao()
    if not cid:
        raiz = sorted(c.categorias_raiz(), key=lambda x: x["name"])
        return {"id": "", "caminho": [], "filhas": [{"id": x["id"], "nome": x["name"]} for x in raiz]}
    cat = c.categoria(cid)
    filhas = sorted(cat.get("children_categories") or [],
                    key=lambda x: -(x.get("total_items_in_this_category") or 0))
    return {"id": cat["id"], "nome": cat.get("name"),
            "caminho": [{"id": p["id"], "nome": p["name"]} for p in cat.get("path_from_root") or []],
            "filhas": [{"id": x["id"], "nome": x["name"],
                        "total": x.get("total_items_in_this_category")} for x in filhas]}


def grupos_whatsapp() -> list[str]:
    from .evolution import Evolution
    evo = Evolution()
    if not evo.no_ar():
        raise RuntimeError("o WhatsApp do bot (Evolution API) não está no ar — abra o Docker "
                           "Desktop ou inicie o bot e tente de novo")
    return sorted(evo.grupos(), key=str.lower)


# ── servidor ─────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    server_version = "PainelOfertas"

    def log_message(self, fmt, *args):  # sem poluir a janela
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if not self._host_ok():
            return self._json({"erro": "acesso negado"}, 403)
        url = urlparse(self.path)
        try:
            if url.path == "/":
                corpo = ARQ_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif url.path == "/api/config":
                self._json(ler_tudo())
            elif url.path == "/api/status":
                self._json(status())
            elif url.path == "/api/categorias":
                self._json(categorias((parse_qs(url.query).get("id") or [""])[0]))
            elif url.path == "/api/whatsapp":
                self._json({"grupos": grupos_whatsapp()})
            else:
                self._json({"erro": "não encontrado"}, 404)
        except Exception as e:
            log.warning("Painel %s: %s", url.path, e)
            self._json({"erro": str(e)}, 502)

    def do_POST(self):
        # cabeçalho próprio: outro site aberto no navegador não consegue enviar
        if not self._host_ok() or self.headers.get("X-Painel") != "1":
            return self._json({"erro": "acesso negado"}, 403)
        if urlparse(self.path).path != "/api/config":
            return self._json({"erro": "não encontrado"}, 404)
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            dados = json.loads(self.rfile.read(min(tamanho, 2_000_000)) or b"{}")
            erros = salvar(dados)
        except Exception as e:
            log.exception("Painel: erro ao salvar")
            return self._json({"ok": False, "erros": [f"Erro ao salvar: {e}"]}, 500)
        if erros:
            return self._json({"ok": False, "erros": erros}, 400)
        self._json({"ok": True, "rodando": bot_rodando()})


def abrir(porta: int = PORTA, navegador: bool = True) -> None:
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", porta), _Handler)
    except OSError:
        print(f"ℹ️  O painel já está aberto: http://127.0.0.1:{porta}")
        if navegador:
            webbrowser.open(f"http://127.0.0.1:{porta}")
        return
    url = f"http://127.0.0.1:{porta}"
    print(f"\n✅ Painel de configuração em {url}")
    print("   (se o navegador não abrir sozinho, copie o endereço acima)")
    print("   Feche esta janela para fechar o painel.\n")
    if navegador:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
