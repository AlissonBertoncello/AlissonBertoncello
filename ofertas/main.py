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
    print(f"ℹ️  Destino: {config.destino}")
    for p in pendencias:
        print(f"⚠️  Falta: {p}")
    if not pendencias:
        print("\n🎉 Tudo pronto! Teste com: uv run python -m ofertas testar")


def _grupos(args):
    """Grupos do config.yaml (ou só os passados em --grupo)."""
    from .config import config
    grupos = config.grupos
    if not grupos:
        raise SystemExit("Nenhum grupo no config.yaml — veja a seção 'grupos'.")
    if getattr(args, "grupo", None):
        pedidos = set(args.grupo)
        grupos = [g for g in grupos if g.chave in pedidos]
        if not grupos:
            raise SystemExit(f"Grupo não encontrado no config.yaml: {', '.join(sorted(pedidos))}")
    return grupos


def cmd_testar(args):
    """Busca e mostra as ofertas de cada grupo, sem enviar nem registrar nada."""
    from . import pipeline
    from .formatter import montar_mensagem
    for g in _grupos(args):
        print(f"\n══ {g.nome} ══")
        brutas = pipeline.coletar(g.categorias)
        boas = pipeline.filtrar(brutas, g.chave)
        boas.sort(key=lambda o: o.desconto or 0, reverse=True)
        for o in boas[:args.n]:
            print(f"[-{o.desconto or 0:>2}%] R$ {o.preco} (de {o.preco_original}) — {o.titulo[:70]}")
        print(f"Total: {len(brutas)} coletadas, {len(boas)} passam nos filtros")
        if args.mensagem and boas:
            top = pipeline.com_link_afiliado(pipeline.escolher(boas, 3))
            if top:
                print("\n── Prévia da mensagem ──")
                print(montar_mensagem(top[0]))
            else:
                print("\n⚠️  Sem prévia: não foi possível gerar o link de afiliado (motivo acima).")


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


def _mostrar_grupos(grupos) -> None:
    print("\n── Grupos ativos ──")
    for g in grupos:
        wa = f"  →  WhatsApp: {g.whatsapp}" if g.whatsapp else ""
        print(f"  • {g.nome}: {', '.join(g.categorias.values())}{wa}")
    print()


def _destino_pronto(grupos):
    """Destino do config.yaml, já checado (no WhatsApp: API no ar, conectado, grupos)."""
    from .config import config
    from .destinos import obter
    destino = obter(config.destino)
    if hasattr(destino, "preparar"):
        try:
            destino.preparar(grupos)
        except Exception as e:
            raise SystemExit(f"❌ {e}")
    return destino


def cmd_whatsapp_login(_):
    from .evolution import ErroWhatsApp, whatsapp_login
    try:
        whatsapp_login()
    except ErroWhatsApp as e:
        raise SystemExit(f"❌ {e}")
    cmd_whatsapp_grupos(None)


def cmd_whatsapp_grupos(_):
    from .evolution import ErroWhatsApp, Evolution
    try:
        evo = Evolution()
        evo.subir()
        grupos = evo.grupos()
    except ErroWhatsApp as e:
        raise SystemExit(f"❌ {e}")
    print("\n── Grupos do WhatsApp do bot (copie o nome para 'whatsapp:' no config.yaml) ──")
    for nome in sorted(grupos, key=str.lower):
        print(f"  • {nome}")
    if not grupos:
        print("  (nenhum — adicione o número do bot aos grupos, como administrador)")


def cmd_ciclo(args):
    from . import pipeline
    grupos = _grupos(args)
    _mostrar_grupos(grupos)
    pipeline.executar_ciclo(_destino_pronto(grupos), grupos)


def cmd_run(args):
    from . import pipeline
    from .config import config
    grupos = _grupos(args)
    _mostrar_grupos(grupos)
    destino = _destino_pronto(grupos)
    log = logging.getLogger("ofertas")
    log.info("Bot iniciado — %d oferta(s) por grupo a cada %d min, destino %s",
             config.max_posts_por_ciclo, config.intervalo_minutos, destino.nome)
    while True:
        inicio = time.monotonic()
        try:
            pipeline.executar_ciclo(destino, grupos)
        except Exception:
            log.exception("Erro no ciclo")
        # o intervalo conta a partir do início do ciclo (a busca leva alguns segundos)
        time.sleep(max(5, config.intervalo_minutos * 60 - (time.monotonic() - inicio)))


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
    pt.add_argument("--grupo", action="append", help="só esse grupo (chave do config.yaml); pode repetir")
    pt.set_defaults(fn=cmd_testar)

    sub.add_parser("diagnostico", help="testa quais caminhos de busca do ML funcionam").set_defaults(fn=cmd_diagnostico)

    pc = sub.add_parser("converter", help="gera o link de afiliado de um produto e mostra a mensagem")
    pc.add_argument("url")
    pc.set_defaults(fn=cmd_converter)

    sub.add_parser("ml-login", help="login único no Mercado Livre (salva a sessão de afiliado)").set_defaults(fn=cmd_ml_login)
    sub.add_parser("instalar-navegador", help="baixa o Chromium (só se não tiver Google Chrome)").set_defaults(fn=cmd_instalar_navegador)

    sub.add_parser("whatsapp-login", help="conecta o número do bot (QR Code) e lista os grupos").set_defaults(fn=cmd_whatsapp_login)
    sub.add_parser("whatsapp-grupos", help="lista os grupos do WhatsApp do bot").set_defaults(fn=cmd_whatsapp_grupos)

    for nome, ajuda, fn in (("ciclo", "roda um único ciclo para os grupos", cmd_ciclo),
                            ("run", "roda os ciclos dos grupos em loop", cmd_run)):
        pr = sub.add_parser(nome, help=ajuda)
        pr.add_argument("--grupo", action="append", help="só esse grupo (chave do config.yaml); pode repetir")
        pr.set_defaults(fn=fn)

    args = p.parse_args()
    args.fn(args)
