# Bot de Ofertas para WhatsApp 🔥

Busca produtos em promoção no **Mercado Livre** usando a **API oficial** e (na etapa 2) envia para um **grupo de WhatsApp**.

## Etapas

| Etapa | O que faz | Status |
|---|---|---|
| 1 | Busca ofertas via API do Mercado Livre, filtra por desconto, evita repetição, gera o **link de afiliado** e monta a mensagem | ✅ pronta |
| 2 | Envia as mensagens para um grupo de WhatsApp | ⏳ a fazer |

Na etapa 1 o destino é o **console**: a mensagem aparece no terminal e fica salva em `data/saida.jsonl`. O texto já sai no formato do WhatsApp (`*negrito*`, `~riscado~`).

## 🖱️ Jeito fácil (Windows)

1. Preencha o `.env` (veja abaixo).
2. Dê **dois cliques em `BUSCAR_OFERTAS.bat`**: instala o que falta (na primeira vez) e mostra as ofertas encontradas.
3. Para o link de afiliado: **dois cliques em `LOGIN_MERCADOLIVRE.bat`** (uma vez só).
4. Para deixar rodando sozinho, de tempos em tempos: **dois cliques em `INICIAR_BOT.bat`**.

## Instalação (pelo terminal)

Requer o [uv](https://docs.astral.sh/uv/) (ele baixa o Python sozinho).

```bash
uv sync
cp .env.example .env    # no Windows: Copy-Item .env.example .env
```

### Credenciais do Mercado Livre
1. Acesse o [DevCenter do Mercado Livre](https://developers.mercadolivre.com.br/devcenter) e crie um aplicativo.
2. Copie o **App ID** para `ML_CLIENT_ID` e a **Secret Key** para `ML_CLIENT_SECRET` no `.env`.

O bot gera e renova o access token sozinho. Se preferir, cole um token pronto em `ML_ACCESS_TOKEN`.

### Link de afiliado (Mercado Livre Afiliados)
A API oficial não gera link de afiliado, então o bot usa o **Linkbuilder** do painel de afiliados, com a sua sessão logada (mesmo método do bot do Telegram). Precisa do **Google Chrome** instalado.

1. Em `ML_ETIQUETA` no `.env`, coloque a **"Etiqueta em uso"** que aparece no [Linkbuilder](https://www.mercadolivre.com.br/afiliados/linkbuilder).
2. Faça o login uma única vez:
   ```bash
   uv run python -m ofertas ml-login
   ```
   Abre um Chrome normal com um perfil separado (`data/ml_profile`). Faça login na conta de afiliado, confira que o Linkbuilder aparece logado e **feche o navegador**.
3. Teste com um produto qualquer:
   ```bash
   uv run python -m ofertas converter "https://produto.mercadolivre.com.br/MLB-..."
   ```

O link é gerado só para as ofertas escolhidas em cada ciclo. Com `afiliado: true` no `config.yaml` (padrão), **oferta sem link de afiliado não é enviada**. Se a sessão expirar, o log avisa para refazer o `ml-login`. Sem Google Chrome, rode `uv run python -m ofertas instalar-navegador` (o login pode ser recusado pelo ML nesse caso).

## Uso

```bash
uv run python -m ofertas check              # o que falta configurar
uv run python -m ofertas diagnostico        # testa quais caminhos da API funcionam
uv run python -m ofertas testar --mensagem  # busca e mostra as ofertas (não envia/registra nada)
uv run python -m ofertas converter "<link>"  # gera o link de afiliado de um produto
uv run python -m ofertas ciclo              # um ciclo: busca → filtra → escolhe → envia ao destino
uv run python -m ofertas run                # ciclos em loop, a cada intervalo_minutos
uv run pytest                               # testes
```

## Ajustes — `config.yaml`
Intervalo entre ciclos, quantas ofertas por ciclo, desconto mínimo, faixa de preço, palavras bloqueadas, horário ativo e **o que buscar**: palavras-chave (`buscas`) e/ou categorias do ML (`categorias`).

## Estrutura
```
ofertas/
├── main.py              # comandos (check, testar, converter, ml-login, ciclo, run)
├── pipeline.py          # coleta → filtros → escolhe → link de afiliado → envia
├── afiliado_ml.py       # link de afiliado via Linkbuilder (sessão logada)
├── formatter.py         # texto da mensagem (formato WhatsApp)
├── db.py                # SQLite anti-repetição (data/ofertas.db)
├── config.py            # lê .env + config.yaml
├── models.py            # Oferta
├── sources/
│   ├── mercadolivre.py  # cliente da API oficial (OAuth, busca, mais vendidos, catálogo)
│   └── ml_pagina.py     # plano B: página de ofertas do ML
└── destinos/
    ├── __init__.py      # interface Destino (etapa 2 pluga o WhatsApp aqui)
    └── console.py       # destino da etapa 1
```

## Uso responsável
- **Divulgação**: avise no grupo que os links são de afiliado (ex: *"Contém links de afiliado; podemos receber comissão, sem custo extra para você."*).
- Respeite os termos da API do Mercado Livre e não abuse da frequência de busca (os padrões do `config.yaml` são comedidos).
- Os preços mudam a qualquer momento; a mensagem reflete o preço no momento da coleta.

## Problemas comuns

**`uv` não é reconhecido** — use o `BUSCAR_OFERTAS.bat` (ele instala o uv), ou rode `winget install astral-sh.uv` e **feche e reabra** o PowerShell.

**`Failed to spawn: python` / "Controle de Aplicativo bloqueou este arquivo"** — é o Smart App Control do Windows 11. Aperte **Windows**, digite `Controle inteligente de aplicativos`, marque **Desativado** e reinicie o PC (o antivírus continua ativo).

**Erro 403 na busca** — o ML bloqueia a busca (`/sites/MLB/search`) para a maioria dos apps. O bot contorna sozinho: usa os **mais vendidos** de cada categoria e a **busca no catálogo** da API; se nada disso responder, lê a **página de ofertas** do ML (`modo: auto` no `config.yaml`). Rode `uv run python -m ofertas diagnostico` para ver quais caminhos funcionam para o seu app.
