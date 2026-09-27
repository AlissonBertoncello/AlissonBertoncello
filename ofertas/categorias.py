"""Menu de categorias do Mercado Livre (escolhida ao iniciar o bot)."""

# id: nome (categorias principais do Mercado Livre Brasil)
CATEGORIAS: dict[str, str] = {
    "MLB1648": "Informática",
    "MLB1000": "Eletrônicos, Áudio e Vídeo",
    "MLB1051": "Celulares e Telefones",
    "MLB1144": "Games",
    "MLB1574": "Casa, Móveis e Decoração",
    "MLB5726": "Eletrodomésticos",
    "MLB1276": "Esportes e Fitness",
    "MLB1430": "Calçados, Roupas e Bolsas",
    "MLB1246": "Beleza e Cuidado Pessoal",
    "MLB264586": "Saúde",
    "MLB1132": "Brinquedos e Hobbies",
    "MLB1384": "Bebês",
    "MLB1071": "Animais",
    "MLB5672": "Acessórios para Veículos",
    "MLB1500": "Construção",
    "MLB263532": "Ferramentas",
    "MLB1196": "Livros, Revistas e Comics",
}


def resolver(escolha: str) -> tuple[str, str] | None:
    """"3", "MLB1051" ou parte do nome ("celular") -> (id, nome)."""
    escolha = escolha.strip()
    if not escolha:
        return None
    itens = list(CATEGORIAS.items())
    if escolha.isdigit() and 1 <= int(escolha) <= len(itens):
        return itens[int(escolha) - 1]
    if escolha.upper().startswith("MLB"):
        cid = escolha.upper()
        return cid, CATEGORIAS.get(cid, cid)
    achadas = [(k, v) for k, v in itens if escolha.lower() in v.lower()]
    return achadas[0] if len(achadas) == 1 else None


def perguntar() -> tuple[str, str]:
    """Mostra o menu e pergunta até receber uma categoria válida."""
    print("\n── Em qual categoria buscar as ofertas? ──")
    for i, nome in enumerate(CATEGORIAS.values(), 1):
        print(f"  {i:>2}. {nome}")
    while True:
        r = resolver(input("\nDigite o número da categoria: "))
        if r:
            print(f"✅ Categoria: {r[1]} ({r[0]})\n")
            return r
        print("❌ Opção inválida. Digite um dos números da lista.")
