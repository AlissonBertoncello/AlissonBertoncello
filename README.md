# Bot de Ofertas para WhatsApp 🔥

Busca produtos em promoção no **Mercado Livre** usando a **API oficial** e (na etapa 2) envia para um **grupo de WhatsApp**.

## Etapas

| Etapa | O que faz | Status |
|---|---|---|
| 1 | Busca ofertas via API do Mercado Livre, filtra por desconto, evita repetição e monta a mensagem | ✅ pronta |
| 2 | Envia as mensagens para um grupo de WhatsApp | ⏳ a fazer |

Na etapa 1 o destino é o **console**: a mensagem aparece no terminal e fica salva em `data/saida.jsonl`. O texto já sai no formato do WhatsApp (`*negrito*`, `~riscado~`).

## Instalação

Requer o [uv](https://docs.astral.sh/uv/) (ele baixa o Python sozinho).

```bash
uv sync
cp .env.example .env    # no Windows: Copy-Item .env.example .env
```

### Credenciais do Mercado Livre
1. Acesse o [DevCenter do Mercado Livre](https://developers.mercadolivre.com.br/devcenter) e crie um aplicativo.
2. Copie o **App ID** para `ML_CLIENT_ID` e a **Secret Key** para `ML_CLIENT_SECRET` no `.env`.

O bot gera e renova o access token sozinho. Se preferir, cole um token pronto em `ML_ACCESS_TOKEN`.

## Uso

```bash
uv run python -m ofertas check              # o que falta configurar
uv run python -m ofertas testar --mensagem  # busca e mostra as ofertas (não envia/registra nada)
uv run python -m ofertas ciclo              # um ciclo: busca → filtra → escolhe → envia ao destino
uv run python -m ofertas run                # ciclos em loop, a cada intervalo_minutos
uv run pytest                               # testes
```

## Ajustes — `config.yaml`
Intervalo entre ciclos, quantas ofertas por ciclo, desconto mínimo, faixa de preço, palavras bloqueadas, horário ativo e **o que buscar**: palavras-chave (`buscas`) e/ou categorias do ML (`categorias`).

## Estrutura
```
ofertas/
├── main.py              # comandos (check, testar, ciclo, run)
├── pipeline.py          # coleta → filtros → escolhe → envia
├── formatter.py         # texto da mensagem (formato WhatsApp)
├── db.py                # SQLite anti-repetição (data/ofertas.db)
├── config.py            # lê .env + config.yaml
├── models.py            # Oferta
├── sources/
│   └── mercadolivre.py  # cliente da API oficial (OAuth + busca)
└── destinos/
    ├── __init__.py      # interface Destino (etapa 2 pluga o WhatsApp aqui)
    └── console.py       # destino da etapa 1
```

## Uso responsável
- Respeite os termos da API do Mercado Livre e não abuse da frequência de busca (os padrões do `config.yaml` são comedidos).
- Os preços mudam a qualquer momento; a mensagem reflete o preço no momento da coleta.
