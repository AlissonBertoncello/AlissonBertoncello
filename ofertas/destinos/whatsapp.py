import logging
import time

from ..config import config
from ..evolution import ErroWhatsApp, Evolution
from ..models import Grupo, Oferta

log = logging.getLogger("ofertas.whatsapp")


class WhatsApp:
    """Envia a oferta (foto + legenda) para os grupos do WhatsApp via Evolution API."""
    nome = "whatsapp"

    def __init__(self, evolution: Evolution | None = None):
        self.evo = evolution or Evolution()

    def preparar(self, grupos: list[Grupo]) -> None:
        """Checa tudo antes de começar: API no ar, número conectado e grupos existentes."""
        self.evo.subir()
        estado = self.evo.aguardar_conexao(45)  # logo após iniciar, ainda está reconectando
        if estado != "open":
            raise ErroWhatsApp(f"WhatsApp do bot não está conectado (estado: {estado}) — "
                               "rode o LOGIN_WHATSAPP.bat")
        for g in grupos:
            if not g.whatsapp:
                raise ErroWhatsApp(f"O grupo '{g.chave}' não tem 'whatsapp:' no config.yaml")
            for alvo in g.whatsapp:
                self.evo.id_do_grupo(alvo)
        log.info("WhatsApp pronto: %d grupo(s) encontrados", sum(len(g.whatsapp) for g in grupos))

    def enviar(self, oferta: Oferta, mensagem: str, grupo: Grupo) -> None:
        """Mesma oferta para todos os grupos do WhatsApp da lista, com pausa entre eles.
        Só dá erro se não conseguir enviar para nenhum."""
        if not grupo.whatsapp:
            raise ErroWhatsApp(f"O grupo '{grupo.chave}' não tem 'whatsapp:' no config.yaml")
        erros = []
        for i, alvo in enumerate(grupo.whatsapp):
            if i:
                time.sleep(config.espacamento_segundos)
            rotulo = grupo.nome if len(grupo.whatsapp) == 1 else f"{grupo.nome} → {alvo}"
            try:
                self._enviar_um(oferta, mensagem, self.evo.id_do_grupo(alvo), rotulo)
            except ErroWhatsApp as e:
                if len(grupo.whatsapp) == 1:
                    raise
                log.error("[%s] falha ao enviar '%s': %s", rotulo, oferta.titulo[:60], e)
                erros.append(e)
        if erros and len(erros) == len(grupo.whatsapp):
            raise ErroWhatsApp(f"nenhum grupo do WhatsApp recebeu a oferta ({erros[-1]})")

    def _enviar_um(self, oferta: Oferta, mensagem: str, destino: str, rotulo: str) -> None:
        if oferta.imagem:
            try:
                self.evo.enviar_foto(destino, oferta.imagem, mensagem)
                log.info("[%s] enviada com foto: %s", rotulo, oferta.titulo[:60])
                return
            except ErroWhatsApp as e:
                log.warning("[%s] foto recusada (%s) — enviando só o texto", rotulo, e)
        self.evo.enviar_texto(destino, mensagem)
        log.info("[%s] enviada: %s", rotulo, oferta.titulo[:60])
