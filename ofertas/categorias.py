"""Categorias do Mercado Livre: nomes usados nos grupos do config.yaml."""

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



def nome(cid: str) -> str:
    return CATEGORIAS.get(cid, cid)
