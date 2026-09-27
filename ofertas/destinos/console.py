import json
from dataclasses import asdict
from datetime import datetime

from ..config import DATA_DIR
from ..models import Grupo, Oferta

ARQ_SAIDA = DATA_DIR / "saida.jsonl"


class Console:
    """Mostra a mensagem no terminal e guarda em data/saida.jsonl (prévia da etapa 2)."""
    nome = "console"

    def enviar(self, oferta: Oferta, mensagem: str, grupo: Grupo) -> None:
        print("─" * 60)
        print(f"📣 Para o grupo: {grupo.nome}\n")
        print(mensagem)
        if oferta.imagem:
            print(f"🖼  {oferta.imagem}")
        registro = {"em": datetime.now().isoformat(timespec="seconds"), "grupo": grupo.chave,
                    "mensagem": mensagem, "oferta": asdict(oferta)}
        with open(ARQ_SAIDA, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
