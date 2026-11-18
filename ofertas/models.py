import datetime as dt
import hashlib
from dataclasses import dataclass, field


@dataclass
class Oferta:
    plataforma: str            # "mercadolivre" (outras fontes no futuro)
    id_produto: str
    titulo: str
    url_produto: str
    preco: float | None = None
    preco_original: float | None = None
    desconto_pct: int | None = None
    imagem: str | None = None
    extra: str | None = None   # frete grátis, loja oficial etc.
    url_afiliado: str = ""     # preenchido pelo Linkbuilder (meli.la/...)
    posicao: int | None = None  # posição no ranking (mais vendidos/catálogo); None = fora de ranking

    @property
    def uid(self) -> str:
        return f"{self.plataforma}:{self.id_produto}"

    @property
    def link(self) -> str:
        """Link que vai na mensagem: o de afiliado, quando houver."""
        return self.url_afiliado or self.url_produto

    @property
    def desconto(self) -> int | None:
        if self.desconto_pct:
            return self.desconto_pct
        if self.preco and self.preco_original and self.preco_original > self.preco:
            return round(100 * (1 - self.preco / self.preco_original))
        return None


@dataclass
class Grupo:
    """Um grupo de destino (na etapa 2, um grupo de WhatsApp) e suas categorias."""
    chave: str
    nome: str
    categorias: dict[str, str] = field(default_factory=dict)  # id: nome, em rodízio
    # nomes exatos (ou ids …@g.us) dos grupos do WhatsApp: todos recebem as mesmas ofertas
    whatsapp: list[str] = field(default_factory=list)
    convite: str = ""          # link de convite do grupo, no fim de cada mensagem
    shopee: list[str] = field(default_factory=list)  # palavras-chave buscadas na Shopee
    bloquear: list[str] = field(default_factory=list)  # palavras proibidas só neste grupo
    ganchos: list[str] = field(default_factory=list)   # frases de abertura, em rodízio
    chamada: str = ""          # texto antes do link de convite ("Manda pro parceiro...")
    chamada_compra: str = ""   # texto antes do link do produto ("🛒 Compre aqui" + " no Mercado Livre:")
    peso_ml: int = 1           # proporção das lojas: a cada peso_ml ciclos do ML,
    peso_shopee: int = 1       # peso_shopee ciclos da Shopee
    # ofertas gerais do ML (todas as categorias, página geral de ofertas + catálogo de reserva)
    ofertas_gerais: bool = False
    departamentos: dict[str, str] = field(default_factory=dict)  # vazio = todos os departamentos
    sem_desconto: bool = False  # aceita os mais vendidos (top 5 do ranking) sem desconto ("Por R$ X")
    etiqueta_ml: str = ""       # etiqueta do Linkbuilder só deste grupo (vazio = a do .env)


@dataclass
class Cupom:
    """Cupom cadastrado no painel (aba Cupons), postado nos horários de cupom."""
    descricao: str
    link: str
    codigo: str = ""
    validade: str = ""          # "AAAA-MM-DD": vale até o fim desse dia; vazio = sem data
    grupos: list[str] = field(default_factory=list)  # chaves dos grupos; vazio = todos

    @property
    def ident(self) -> str:
        return "cupom:" + hashlib.sha1(f"{self.link}|{self.codigo}".encode()).hexdigest()[:12]

    def vale_em(self, dia: dt.date) -> bool:
        if not self.validade:
            return True
        try:
            return dia <= dt.date.fromisoformat(self.validade)
        except ValueError:
            return False

    def para(self, grupo: str) -> bool:
        return not self.grupos or grupo in self.grupos


HORARIOS_CUPOM_PADRAO = ["10:00", "15:00", "20:00"]


@dataclass
class ConfigCupons:
    horarios: list[str] = field(default_factory=lambda: list(HORARIOS_CUPOM_PADRAO))
    shopee_campanhas: bool = False  # busca sozinho as campanhas/cupons da Shopee
    grupos_campanhas: list[str] = field(default_factory=list)  # quem recebe campanhas; vazio = todos
    lista: list[Cupom] = field(default_factory=list)

    @property
    def ligado(self) -> bool:
        return bool(self.horarios and (self.lista or self.shopee_campanhas))
