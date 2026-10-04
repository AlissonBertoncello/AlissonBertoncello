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
    whatsapp: str = ""         # nome exato (ou id …@g.us) do grupo no WhatsApp
    convite: str = ""          # link de convite do grupo, no fim de cada mensagem
    shopee: list[str] = field(default_factory=list)  # palavras-chave buscadas na Shopee
