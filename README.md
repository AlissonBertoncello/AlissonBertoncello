# Bot de Ofertas para WhatsApp 🔥

Busca produtos em promoção no **Mercado Livre** usando a **API oficial** e (na etapa 2) envia para um **grupo de WhatsApp**.

## Etapas

| Etapa | O que faz | Status |
|---|---|---|
| 1 | Busca ofertas via API do Mercado Livre, filtra por desconto, evita repetição, gera o **link de afiliado** e monta a mensagem | ✅ pronta |
| 2 | Envia as ofertas (foto + legenda) para os grupos de WhatsApp via **Evolution API** (gratuita, local) | ✅ pronta |

O destino é escolhido no `config.yaml`: **`console`** (testes: mostra no terminal e salva em `data/saida.jsonl`) ou **`whatsapp`** (envia para os grupos). O texto sai no formato do WhatsApp (`*negrito*`, `~riscado~`).

## 🖱️ Jeito fácil (Windows)

1. Preencha o `.env` (veja abaixo).
2. Dê **dois cliques em `BUSCAR_OFERTAS.bat`**: instala o que falta (na primeira vez) e mostra as ofertas encontradas.
3. Para o link de afiliado: **dois cliques em `LOGIN_MERCADOLIVRE.bat`** (uma vez só).
4. Para deixar rodando sozinho: **dois cliques em `INICIAR_BOT.bat`**.
   O bot roda **todos os grupos** do `config.yaml` numa janela só. A cada ciclo (1 minuto na fase de testes), **cada grupo recebe 1 oferta**, alternando as categorias do grupo.

## 📲 WhatsApp (Evolution API)

O envio usa a [Evolution API](https://doc.evolution-api.com), gratuita, rodando **no seu PC** via Docker. Ela conecta um número de WhatsApp como "aparelho conectado" (igual ao WhatsApp Web).

> ⚠️ Automatizar o WhatsApp não é permitido pelos termos do WhatsApp e o número pode ser **bloqueado**. Use um **número só para o bot**, mantenha um ritmo moderado (ex.: 1 oferta por grupo a cada 30–45 min) e coloque o número como **administrador** dos grupos.

1. Instale o **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** e deixe-o **aberto**.
2. Adicione o número do bot aos grupos do WhatsApp.
3. **Dois cliques em `LOGIN_WHATSAPP.bat`**: sobe a Evolution (na 1ª vez baixa ~1 GB), abre um **QR Code** — leia com o celular do número do bot em *WhatsApp > Aparelhos conectados > Conectar um aparelho* — e lista os grupos.
4. No `config.yaml`, preencha `whatsapp:` de cada grupo com o **nome exato** do grupo e troque `destino: console` por `destino: whatsapp`.
5. **Dois cliques em `INICIAR_BOT.bat`**. Antes de começar, o bot confere se a Evolution está no ar, se o número está conectado e se os grupos existem.

A senha da Evolution (`EVOLUTION_API_KEY`) é gerada sozinha no `.env` no primeiro uso. A sessão do WhatsApp fica salva no Docker — só precisa ler o QR de novo se desconectar o aparelho no celular. Painel da Evolution (opcional): http://localhost:8080/manager

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

O link é gerado só para as ofertas escolhidas em cada ciclo. O link de afiliado é **obrigatório**: oferta sem link de afiliado é descartada (o bot tenta a próxima melhor no lugar). Se a sessão expirar, o log avisa para refazer o `ml-login`. Sem Google Chrome, rode `uv run python -m ofertas instalar-navegador` (o login pode ser recusado pelo ML nesse caso).

## Uso

```bash
uv run python -m ofertas check              # o que falta configurar
uv run python -m ofertas diagnostico        # testa quais caminhos da API funcionam
uv run python -m ofertas testar --mensagem  # busca e mostra as ofertas (não envia/registra nada)
uv run python -m ofertas converter "<link>"  # gera o link de afiliado de um produto
uv run python -m ofertas ciclo              # um ciclo: busca → filtra → escolhe → envia ao destino
uv run python -m ofertas run                # roda todos os grupos em loop, a cada intervalo_minutos
uv run python -m ofertas run --grupo bebe   # só um grupo (chave do config.yaml)
uv run python -m ofertas whatsapp-login     # conecta o número do bot (QR Code) e lista os grupos
uv run python -m ofertas whatsapp-grupos    # lista os grupos do WhatsApp do bot
uv run pytest                               # testes
```

## Grupos — `config.yaml`
Cada grupo tem um nome e uma lista de categorias do ML (a lista de ids está comentada no próprio arquivo). Exemplo:
```yaml
grupos:
  casa_info:
    nome: Ofertas Casa e Informática
    categorias: [MLB1574, MLB1648]
  bebe:
    nome: Ofertas Mamãe e Bebê
    categorias: [MLB1384]
```
A cada ciclo, cada grupo recebe `max_posts_por_ciclo` oferta(s), alternando as categorias (se a categoria da vez não tiver oferta nova, usa a próxima). O mesmo produto — ou variação dele (cor, tamanho) — não se repete **no mesmo grupo** por `nao_repetir_dias`.

**De onde vêm as ofertas de cada categoria** (`modo: auto`, padrão):
- **Mais vendidos** da API do ML, da categoria e das subcategorias diretas (em rodízio, `subcategorias_por_busca` por vez);
- **Página de ofertas** do ML da categoria (`mercadolivre.com.br/ofertas?category=...`, só produtos em promoção, ~48 por página), em rodízio de páginas (`paginas_ofertas` por vez, até `paginas_ofertas_max`).

Depois, só passam as que atendem aos filtros (desconto mínimo etc.). Os links de afiliado de todos os grupos são gerados num único lote.

## Ajustes — `config.yaml`
Intervalo entre ciclos, quantas ofertas por ciclo, desconto mínimo, faixa de preço, palavras bloqueadas, horário ativo e os **grupos** (acima).

## Estrutura
```
ofertas/
├── main.py              # comandos (check, testar, converter, ml-login, ciclo, run)
├── pipeline.py          # coleta → filtros → escolhe → link de afiliado → envia
├── afiliado_ml.py       # link de afiliado via Linkbuilder (sessão logada)
├── evolution.py         # cliente da Evolution API (Docker, QR Code, grupos, envio)
├── formatter.py         # texto da mensagem (formato WhatsApp)
├── db.py                # SQLite anti-repetição (data/ofertas.db)
├── config.py            # lê .env + config.yaml
├── models.py            # Oferta
├── sources/
│   ├── mercadolivre.py  # cliente da API oficial (OAuth, busca, mais vendidos, catálogo)
│   └── ml_pagina.py     # plano B: página de ofertas do ML
└── destinos/
    ├── __init__.py      # interface Destino
    ├── console.py       # testes: mostra no terminal
    └── whatsapp.py      # envia foto + legenda para o grupo
evolution/
└── docker-compose.yml   # Evolution API v2.3.7 + Postgres + Redis (local)
```

## Uso responsável
- **Divulgação**: avise no grupo que os links são de afiliado (ex: *"Contém links de afiliado; podemos receber comissão, sem custo extra para você."*).
- Respeite os termos da API do Mercado Livre e não abuse da frequência de busca (os padrões do `config.yaml` são comedidos).
- Os preços mudam a qualquer momento; a mensagem reflete o preço no momento da coleta.

## Problemas comuns

**`uv` não é reconhecido** — use o `BUSCAR_OFERTAS.bat` (ele instala o uv), ou rode `winget install astral-sh.uv` e **feche e reabra** o PowerShell.

**`Failed to spawn: python` / "Controle de Aplicativo bloqueou este arquivo"** — é o Smart App Control do Windows 11. Aperte **Windows**, digite `Controle inteligente de aplicativos`, marque **Desativado** e reinicie o PC (o antivírus continua ativo).

**Erro 403 na busca** — o ML bloqueia a busca (`/sites/MLB/search`) para a maioria dos apps. O bot contorna sozinho: usa os **mais vendidos** de cada categoria e das suas **subcategorias** (em rodízio, `subcategorias_por_busca` por vez) e a **busca no catálogo** da API; se nada disso responder, lê a **página de ofertas** do ML (`modo: auto` no `config.yaml`). Rode `uv run python -m ofertas diagnostico` para ver quais caminhos funcionam para o seu app.

**WhatsApp: "Docker não encontrado" / "docker compose falhou"** — instale o Docker Desktop e deixe-o aberto antes de rodar o bot.

**WhatsApp: "não conseguiu gerar o QR Code"** — a Evolution não está alcançando o WhatsApp: confira a internet, antivírus/firewall, e rode o `LOGIN_WHATSAPP.bat` de novo.

**WhatsApp: "não está conectado"** — o aparelho foi desconectado no celular; rode o `LOGIN_WHATSAPP.bat`.

**WhatsApp: "Grupo ... não encontrado"** — o nome em `whatsapp:` precisa ser igual ao do grupo (veja a lista com `whatsapp-grupos`) e o número do bot precisa estar no grupo.
