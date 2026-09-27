import logging

from ..evolution import ErroWhatsApp, Evolution
from ..models import Grupo, Oferta

log = logging.getLogger("ofertas.whatsapp")


class WhatsApp:
    """Envia a oferta (foto + legenda) para o grupo do WhatsApp via Evolution API."""
    nome = "whatsapp"

    def __init__(self, evolution: Evolution | None = None):
        self.evo = evolution or Evolution()

    def preparar(self, grupos: list[Grupo]) -> None:
        """Checa tudo antes de começar: API no ar, número conectado e grupos existentes."""
        self.evo.subir()
        estado = self.evo.estado()
        if estado != "open":
            raise ErroWhatsApp(f"WhatsApp do bot não está conectado (estado: {estado}) — "
                               "rode o LOGIN_WHATSAPP.bat")
        for g in grupos:
            if not g.whatsapp:
                raise ErroWhatsApp(f"O grupo '{g.chave}' não tem 'whatsapp:' no config.yaml")
            self.evo.id_do_grupo(g.whatsapp)
        log.info("WhatsApp pronto: %d grupo(s) encontrados", len(grupos))

    def enviar(self, oferta: Oferta, mensagem: str, grupo: Grupo) -> None:
        if not grupo.whatsapp:
            raise ErroWhatsApp(f"O grupo '{grupo.chave}' não tem 'whatsapp:' no config.yaml")
        destino = self.evo.id_do_grupo(grupo.whatsapp)
        if oferta.imagem:
            try:
                self.evo.enviar_foto(destino, oferta.imagem, mensagem)
                log.info("[%s] enviada com foto: %s", grupo.nome, oferta.titulo[:60])
                return
            except ErroWhatsApp as e:
                log.warning("[%s] foto recusada (%s) — enviando só o texto", grupo.nome, e)
        self.evo.enviar_texto(destino, mensagem)
        log.info("[%s] enviada: %s", grupo.nome, oferta.titulo[:60])
