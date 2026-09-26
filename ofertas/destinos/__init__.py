"""Destinos: para onde as ofertas escolhidas são enviadas.

Etapa 1: "console" (mostra no terminal e salva em data/saida.jsonl).
Etapa 2: "whatsapp" (envia para o grupo) — basta criar um módulo com a
mesma função enviar(oferta, mensagem) e registrar abaixo.
"""
from typing import Protocol

from ..models import Oferta


class Destino(Protocol):
    nome: str

    def enviar(self, oferta: Oferta, mensagem: str) -> None: ...


def obter(nome: str) -> Destino:
    if nome == "console":
        from .console import Console
        return Console()
    if nome == "whatsapp":
        raise SystemExit("Destino 'whatsapp' ainda não implementado (etapa 2). "
                         "Use destino: console no config.yaml.")
    raise SystemExit(f"Destino desconhecido no config.yaml: {nome!r}")
