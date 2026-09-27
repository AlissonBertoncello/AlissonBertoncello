import argparse
import logging
import sys
import time


def _log():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def cmd_check(_):
    from .config import config, verificar
    pendencias = verificar()
    print("── Checagem da configuração ──")
    if config.ml_access_token:
        print("✅ Access token do Mercado Livre (fixo)")
    elif config.ml_client_id and config.ml_client_secret:
        print("✅ Credenciais do app do Mercado Livre")
    if config.ml_etiqueta:
        print(f"✅ Etiqueta de afiliado: {config.ml_etiqueta}")
    from .afiliado_ml import tem_sessao
    if tem_sessao():
        print("✅ Sessão do Mercado Livre")
    print(f"ℹ️  Link de afiliado: {'obrigatório' if config.ml_afiliado else 'desligado'}")
    print(f"ℹ️  Destino: {config.destino}")
    for p in pendencias:
        print(f"⚠️  Falta: {p}")
    if not pendencias:
        print("\n🎉 Tudo pronto! Teste com: uv run python -m ofertas testar")


def cmd_testar(args):
    """Busca e mostra as ofertas, sem enviar nem registrar nada."""
    from . import pipeline
    from .formatter import montar_mensagem
    brutas = pipeline.coletar()
    boas = pipeline.filtrar(brutas)
    boas.sort(key=lambda o: o.desconto or 0, reverse=True)
    for o in boas[:args.n]:
        print(f"[-{o.desconto or 0:>2}%] R$ {o.preco} (de {o.preco_original}) — {o.titulo[:70]}")
    print(f"\nTotal: {len(brutas)} coletadas, {len(boas)} passam nos filtros")
    if args.mensagem and boas:
        print("\n── Prévia da mensagem ──")
        print(montar_mensagem(boas[0]))


def cmd_diagnostico(_):
    """Testa cada caminho de busca (API e página) e mostra qual funciona para o seu app."""
    from .config import config
    from .sources import ml_pagina
    from .sources.mercadolivre import ClienteML, ErroAPI
    c = ClienteML.do_config()
    site = str(config.fonte_ml.get("site") or "MLB")

    def testar(nome, fn):
        try:
            r = fn()
            print(f"✅ {nome}: {r}")
            return True
        except Exception as e:
            print(f"❌ {nome}: {str(e)[:160]}")
            return False

    print("── Diagnóstico do Mercado Livre ──")
    if not testar("Token", lambda: "ok" if c.token() else "vazio"):
        return
    testar("Busca /sites/search", lambda: f"{len(c.buscar(site, q='fone', limite=5))} itens")
    dest: list = []
    testar("Mais vendidos /highlights", lambda: f"{len(dest.extend(c.destaques(site, 'MLB1648')) or dest)} itens")
    ids_item = [d["id"] for d in dest if d.get("type") == "ITEM"][:3]
    ids_prod = [d["id"] for d in dest if d.get("type") == "PRODUCT"][:1]
    if ids_item:
        testar("Anúncios /items", lambda: f"{len(c.itens(ids_item))} de {len(ids_item)}")
    if ids_prod:
        testar("Produto /products", lambda: c.produto(ids_prod[0]).get("name", "?")[:50])
    testar("Catálogo /products/search", lambda: f"{len(c.buscar_produtos(site, 'fone', 5))} produtos")
    testar("Página de ofertas (sem API)", lambda: f"{len(ml_pagina.buscar_ofertas({'': 'todas'}))} ofertas")


def cmd_converter(args):
    from .formatter import montar_mensagem
    from .sources import mercadolivre
    if not mercadolivre.e_link_ml(args.url):
        raise SystemExit("Link não reconhecido (esperado: Mercado Livre).")
    o = mercadolivre.converter(args.url)
    print(f"Título:        {o.titulo}")
    print(f"Preço:         {o.preco}  (de {o.preco_original})  -{o.desconto or 0}%")
    print(f"Produto:       {o.url_produto}")
    print(f"Link afiliado: {o.url_afiliado}")
    print("\n── Prévia da mensagem ──")
    print(montar_mensagem(o))


def cmd_ml_login(_):
    from .afiliado_ml import ml_login
    ml_login()


def cmd_instalar_navegador(_):
    import subprocess
    from . import config  # noqa: F401 — define PLAYWRIGHT_BROWSERS_PATH (data/pw-browsers)
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    if r.returncode == 0:
        print("✅ Chromium instalado em data/pw-browsers")
    raise SystemExit(r.returncode)


def cmd_ciclo(_):
    from . import pipeline
    from .config import config
    from .destinos import obter
    pipeline.executar_ciclo(obter(config.destino))


def cmd_run(_):
    from . import pipeline
    from .config import config
    from .destinos import obter
    destino = obter(config.destino)
    log = logging.getLogger("ofertas")
    log.info("Bot iniciado — ciclo a cada %d min, destino %s",
             config.intervalo_minutos, destino.nome)
    while True:
        try:
            pipeline.executar_ciclo(destino)
        except Exception:
            log.exception("Erro no ciclo")
        time.sleep(config.intervalo_minutos * 60)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _log()

    p = argparse.ArgumentParser(prog="ofertas",
                                description="Ofertas do Mercado Livre para grupo de WhatsApp")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="mostra o que falta configurar").set_defaults(fn=cmd_check)

    pt = sub.add_parser("testar", help="busca ofertas e mostra (não envia nada)")
    pt.add_argument("-n", type=int, default=15, help="quantas mostrar (padrão 15)")
    pt.add_argument("--mensagem", action="store_true", help="mostra a prévia da mensagem da melhor oferta")
    pt.set_defaults(fn=cmd_testar)

    sub.add_parser("diagnostico", help="testa quais caminhos de busca do ML funcionam").set_defaults(fn=cmd_diagnostico)

    pc = sub.add_parser("converter", help="gera o link de afiliado de um produto e mostra a mensagem")
    pc.add_argument("url")
    pc.set_defaults(fn=cmd_converter)

    sub.add_parser("ml-login", help="login único no Mercado Livre (salva a sessão de afiliado)").set_defaults(fn=cmd_ml_login)
    sub.add_parser("instalar-navegador", help="baixa o Chromium (só se não tiver Google Chrome)").set_defaults(fn=cmd_instalar_navegador)

    sub.add_parser("ciclo", help="roda um único ciclo de busca e envio").set_defaults(fn=cmd_ciclo)
    sub.add_parser("run", help="roda os ciclos em loop").set_defaults(fn=cmd_run)

    args = p.parse_args()
    args.fn(args)
