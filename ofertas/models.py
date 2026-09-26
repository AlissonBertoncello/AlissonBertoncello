from dataclasses import dataclass


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
