"""Destinos: para onde as ofertas escolhidas são enviadas.

Etapa 1: "console" (mostra no terminal e salva em data/saida.jsonl).
Etapa 2: "whatsapp" (foto + legenda no grupo, via Evolution API).
Um destino pode ter preparar(grupos), chamado uma vez antes dos ciclos.
"""
from typing import Protocol

from ..models import Grupo, Oferta


class Destino(Protocol):
    nome: str

    def enviar(self, oferta: Oferta, mensagem: str, grupo: Grupo) -> None: ...


def obter(nome: str) -> Destino:
    if nome == "console":
        from .console import Console
        return Console()
    if nome == "whatsapp":
        from .whatsapp import WhatsApp
        return WhatsApp()
    raise SystemExit(f"Destino desconhecido no config.yaml: {nome!r}")
