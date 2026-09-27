import json
from dataclasses import asdict
from datetime import datetime

from ..config import DATA_DIR
from ..models import Oferta

ARQ_SAIDA = DATA_DIR / "saida.jsonl"


class Console:
    """Mostra a mensagem no terminal e guarda em data/saida.jsonl (prévia da etapa 2)."""
    nome = "console"

    def enviar(self, oferta: Oferta, mensagem: str) -> None:
        print("─" * 60)
        print(mensagem)
        if oferta.imagem:
            print(f"🖼  {oferta.imagem}")
        if oferta.plataforma == "mercadolivre" and not oferta.url_afiliado:
            print("⚠️  ATENÇÃO: este link NÃO é de afiliado (a geração falhou — veja o motivo"
                  " na linha 'Linkbuilder ML falhou' acima).")
        registro = {"em": datetime.now().isoformat(timespec="seconds"),
                    "mensagem": mensagem, "oferta": asdict(oferta)}
        with open(ARQ_SAIDA, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
