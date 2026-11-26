"""Descoberta adicional de ofertas por ranking e catálogo do Mercado Livre.

Opt-in: fontes.mercadolivre.ranking_adicional: true
Não altera as fontes existentes nem gera links (o pipeline faz isso).
"""
import logging

from ..models import Oferta

log = logging.getLogger("ofertas.ml.ranking_adicional")


def descobrir(cliente, site: str, categoria: str, limite: int = 20) -> list[Oferta]:
    """Ranking -> PRODUCT -> anúncios com preço; ignora dados incompletos.

    USER_PRODUCT não expõe nome/imagem nesta credencial (403), por isso fica
    fora até existir fonte confiável desses campos.
    """
    from .mercadolivre import produto_para_oferta, ErroAPI, item_para_oferta

    try:
        ranking = cliente.destaques(site, categoria)
    except Exception as exc:
        log.warning("Ranking adicional %s: %s", categoria, exc)
        return []

    saida: list[Oferta] = []
    vistos: set[str] = set()
    for posicao, entrada in enumerate(ranking[:max(1, limite)], 1):
        if entrada.get("type") not in ("PRODUCT", "ITEM"):
            continue
        pid = entrada.get("id")
        if not pid or pid in vistos:
            continue
        vistos.add(pid)
        try:
            if entrada.get("type") == "ITEM":
                for item in cliente.itens([pid]):
                    oferta = item_para_oferta(item)
                    if (oferta and oferta.imagem and oferta.preco is not None
                            and oferta.preco_original and 0 < oferta.preco < oferta.preco_original):
                        oferta.posicao = posicao
                        saida.append(oferta)
                continue
            produto = cliente.produto(pid)
            if not produto.get("name") or not produto.get("pictures"):
                continue
            anuncios = []
            vencedor = produto.get("buy_box_winner") or {}
            if vencedor:
                anuncios.append(vencedor)
            try:
                anuncios.extend(cliente.itens_do_produto(pid))
            except ErroAPI:
                # O catálogo continua utilizável quando a listagem não é autorizada.
                pass
            if vencedor.get("item_id") and (vencedor.get("price") is None
                                             or vencedor.get("original_price") is None):
                try:
                    for item in cliente.itens([vencedor["item_id"]]):
                        oferta = item_para_oferta(item)
                        if (oferta and oferta.imagem and oferta.preco is not None
                                and oferta.preco_original and 0 < oferta.preco < oferta.preco_original):
                            oferta.posicao = posicao
                            saida.append(oferta)
                            break
                except ErroAPI:
                    pass
            # Não usar apenas o menor preço: exigir desconto verificável.
            elegiveis = [a for a in anuncios
                         if a.get("item_id") and a.get("price") is not None
                         and a.get("original_price") is not None
                         and 0 < float(a["price"]) < float(a["original_price"])]
            if not elegiveis:
                continue
            anuncio = max(elegiveis, key=lambda a: (
                1 - float(a["price"]) / float(a["original_price"]),
                -float(a["price"]),
            ))
            oferta = produto_para_oferta(produto, anuncio)
            if not oferta or not oferta.imagem or not oferta.preco_original:
                continue
            # URL do anúncio específico (a mesma forma aprovada pelo Linkbuilder).
            oferta.url_produto = (
                "https://produto.mercadolivre.com.br/"
                + anuncio["item_id"].replace("MLB", "MLB-", 1)
                + "-_JM"
            )
            oferta.id_produto = str(anuncio["item_id"])
            oferta.posicao = posicao
            saida.append(oferta)
        except (ValueError, TypeError, KeyError, RuntimeError) as exc:
            log.debug("Produto adicional %s ignorado: %s", pid, exc)
        except Exception as exc:
            log.warning("Produto adicional %s: %s", pid, exc)
    return saida
