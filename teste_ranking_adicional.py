"""Diagnostico de ranking ML, sem WhatsApp nem alteracao de configuracao.

Uso: uv run python teste_ranking_adicional.py
Opcional (exige ml-login nesta pasta): uv run python teste_ranking_adicional.py --afiliados
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from ofertas.sources.mercadolivre import ClienteML
from ofertas.sources.ml_ranking_adicional import descobrir

CATEGORIAS = {
    "Ferramentas": "MLB263532",
    "Moda fitness": "MLB270215",
    "Leggings": "MLB270216",
    "Conjuntos fitness": "MLB270220",
    "Tops fitness": "MLB270229",
    "Moda geral": "MLB1430",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--afiliados", action="store_true",
                        help="Gera links via Linkbuilder no perfil desta pasta, sem publicar")
    parser.add_argument("--limite", type=int, default=20)
    args = parser.parse_args()
    cliente = ClienteML.do_config()
    resultados = []
    ids = set()
    for nome, categoria in CATEGORIAS.items():
        try:
            ofertas = descobrir(cliente, "MLB", categoria, args.limite)
        except Exception as exc:
            print(f"{nome}: ERRO {exc}")
            continue
        novas = [o for o in ofertas if o.id_produto not in ids]
        ids.update(o.id_produto for o in novas)
        print(f"{nome}: {len(ofertas)} ofertas, {len(novas)} novas")
        resultados.extend(novas)
    validas = [o for o in resultados if o.titulo and o.imagem and o.preco_original
               and o.preco is not None and o.preco < o.preco_original
               and urlparse(o.url_produto).hostname == "produto.mercadolivre.com.br"]
    print(f"TOTAL: {len(resultados)} | DADOS COMPLETOS: {len(validas)}")
    if args.afiliados and validas:
        from ofertas.afiliado_ml import gerar_links_afiliado
        try:
            gerar_links_afiliado(validas[:10])
        except Exception as exc:
            print(f"LINKBUILDER: {type(exc).__name__}: {exc}")
    relatorio = {
        "total": len(resultados),
        "dados_completos": len(validas),
        "ofertas": [{
            "id": o.id_produto,
            "titulo": o.titulo,
            "preco": o.preco,
            "preco_original": o.preco_original,
            "imagem": o.imagem,
            "url_produto": o.url_produto,
            "url_afiliado": o.url_afiliado,
        } for o in resultados],
    }
    destino = Path("teste_ranking_adicional_resultado.json")
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatorio: {destino.resolve()}")
    print("Nenhuma mensagem enviada ao WhatsApp.")


if __name__ == "__main__":
    main()
