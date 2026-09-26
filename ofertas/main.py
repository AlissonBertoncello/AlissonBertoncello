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

    sub.add_parser("ciclo", help="roda um único ciclo de busca e envio").set_defaults(fn=cmd_ciclo)
    sub.add_parser("run", help="roda os ciclos em loop").set_defaults(fn=cmd_run)

    args = p.parse_args()
    args.fn(args)
