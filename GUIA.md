# Guia completo — Bot de Ofertas (Mercado Livre → WhatsApp)

Este guia leva você do zero até o bot rodando, e explica o que fazer em cada erro que pode aparecer.

**Sumário**
1. [O que o bot faz](#1-o-que-o-bot-faz)
2. [O que você precisa ter](#2-o-que-você-precisa-ter)
3. [Instalação (uma vez só)](#3-instalação-uma-vez-só)
4. [Configuração](#4-configuração)
5. [Login de afiliado do Mercado Livre](#5-login-de-afiliado-do-mercado-livre)
6. [Conectar o WhatsApp do bot](#6-conectar-o-whatsapp-do-bot)
7. [Testar antes de enviar para os grupos](#7-testar-antes-de-enviar-para-os-grupos)
8. [Colocar para valer](#8-colocar-para-valer)
9. [Uso no dia a dia](#9-uso-no-dia-a-dia)
10. [Atualizar o projeto](#10-atualizar-o-projeto)
11. [Referência do `config.yaml`](#11-referência-do-configyaml)
12. [Comandos (terminal)](#12-comandos-terminal)
13. [Erros e o que fazer](#13-erros-e-o-que-fazer)
14. [Segurança e uso responsável](#14-segurança-e-uso-responsável)

---

## 1. O que o bot faz

A cada ciclo (por exemplo, a cada 45 minutos), para **cada grupo** configurado:

1. **Busca promoções** no Mercado Livre nas categorias do grupo, alternando as categorias a cada ciclo:
   - **mais vendidos** pela API oficial do Mercado Livre (categoria + subcategorias, em rodízio);
   - **página de ofertas** do Mercado Livre da categoria (só produtos em promoção, uma página por vez, em rodízio).
2. **Filtra**: desconto mínimo, faixa de preço, palavras bloqueadas, e **não repete** produto (nem variação de cor/tamanho) no mesmo grupo dentro do prazo.
3. **Escolhe** a melhor oferta (maior desconto).
4. **Gera o link de afiliado** (`meli.la/...`). **Oferta sem link de afiliado é sempre descartada.**
5. **Envia** para o grupo do WhatsApp: **foto do produto + legenda** com preço "de/por", desconto e link.

```
Mercado Livre ──► filtros ──► melhor oferta ──► link de afiliado ──► WhatsApp (grupo)
 (API + ofertas)                                  (Linkbuilder)        (Evolution API)
```

Tudo roda **no seu PC** (Windows). Não há mensalidade.

---

## 2. O que você precisa ter

| Item | Para quê | Onde |
|---|---|---|
| Conta de **Afiliados do Mercado Livre** | gerar os links com comissão | https://www.mercadolivre.com.br/afiliados |
| **Aplicativo** no DevCenter do Mercado Livre | usar a API oficial (App ID e Secret Key) | https://developers.mercadolivre.com.br/devcenter |
| **Google Chrome** | login de afiliado e geração dos links | https://www.google.com/chrome |
| **Docker Desktop** | rodar a Evolution API (WhatsApp) | https://www.docker.com/products/docker-desktop/ |
| **Número de WhatsApp só para o bot** | enviar as mensagens | chip separado (nunca use o seu pessoal) |
| Grupos do WhatsApp com o número do bot | destino das ofertas | o número do bot deve ser **administrador** |

O **uv** (que instala o Python e as bibliotecas) é instalado automaticamente pelo `BUSCAR_OFERTAS.bat`.

---

## 3. Instalação (uma vez só)

### 3.1 Baixar o projeto
1. Abra https://github.com/AlissonBertoncello/AlissonBertoncello
2. Clique no botão verde **Code → Download ZIP**.
3. Extraia para uma pasta sem acentos no caminho, por exemplo `C:\bot-ofertas`.

### 3.2 Instalar o Python e as bibliotecas
Dê **dois cliques em `BUSCAR_OFERTAS.bat`**. Na primeira vez ele instala o `uv` e as dependências (pode demorar alguns minutos). Se ele pedir, feche a janela e abra de novo.

> Ele vai reclamar que faltam credenciais — normal, você configura no passo 4.

### 3.3 Instalar o Google Chrome
Se ainda não tiver, instale o Google Chrome normalmente.

### 3.4 Instalar o Docker Desktop
1. Baixe e instale o **Docker Desktop**. Se o instalador perguntar, deixe marcado **"Use WSL 2"**.
2. Reinicie o PC se ele pedir.
3. Abra o Docker Desktop e espere aparecer **"Engine running"** (canto inferior esquerdo, verde).

**Como saber se o Docker está funcionando** — no PowerShell:
```powershell
docker version
```
Deve mostrar as partes **Client** e **Server**. Teste completo:
```powershell
docker run hello-world
```
Deve aparecer **"Hello from Docker!"**.

Se o Docker mostrar erro de **virtualização**, veja a seção [13.5](#135-docker).

---

## 4. Configuração

São dois arquivos na pasta do projeto:
- **`.env`** → senhas e chaves (**nunca compartilhe**);
- **`config.yaml`** → grupos, categorias, filtros e horários.

### 4.1 Criar o `.env`
No PowerShell, dentro da pasta do projeto:
```powershell
cd C:\bot-ofertas
Copy-Item .env.example .env
notepad .env
```
Preencha:

| Chave | O que colocar | Onde encontrar |
|---|---|---|
| `ML_CLIENT_ID` | App ID do seu aplicativo | DevCenter do Mercado Livre |
| `ML_CLIENT_SECRET` | Secret Key do aplicativo | DevCenter do Mercado Livre |
| `ML_ETIQUETA` | a **"Etiqueta em uso"** | página do [Linkbuilder](https://www.mercadolivre.com.br/afiliados/linkbuilder), logado na conta de afiliado |
| `EVOLUTION_API_KEY` | deixe **vazio** | o bot gera sozinho no primeiro uso |

Regras: sem aspas, sem espaços, exatamente como aparece. Ex.: `ML_ETIQUETA=minhaetiqueta`.

> No Windows, arquivos que começam com ponto podem não aparecer no Explorador. Use o `notepad .env` como acima.

### 4.2 Configurar os grupos no `config.yaml`
```powershell
notepad config.yaml
```
Cada grupo tem um nome, as categorias do Mercado Livre e o nome do grupo no WhatsApp:
```yaml
grupos:
  casa_info:
    nome: Ofertas Casa e Informática
    categorias: [MLB1574, MLB1648]     # Casa, Móveis e Decoração · Informática
    whatsapp: "Nome exato do grupo no WhatsApp"
  bebe:
    nome: Ofertas Mamãe e Bebê
    categorias: [MLB1384]              # Bebês
    whatsapp: "Nome exato do outro grupo"
```
- **Para criar um grupo novo:** copie um bloco inteiro, mude a chave (`casa_info` → `pet`, por exemplo), o nome, as categorias e o `whatsapp`.
- A **lista de categorias** (ids `MLB...`) está comentada dentro do próprio `config.yaml`.
- O `whatsapp:` você preenche depois do passo 6 (lá aparece a lista com os nomes exatos).
- O `convite:` é o **link de convite do grupo** (no WhatsApp: grupo → *Convidar via link*). Ele vai no fim de cada oferta, com o texto *"💬 Envie essa oferta para uma amiga!"*. Substitua o texto entre colchetes pelo link, **entre aspas**: `convite: "https://chat.whatsapp.com/XXXX"`. Enquanto estiver o texto entre colchetes, essas duas linhas não aparecem na mensagem.

Atenção ao formato do YAML: use **espaços** (nunca TAB) e mantenha o alinhamento igual ao exemplo.

---

## 5. Login de afiliado do Mercado Livre

Necessário para gerar os links `meli.la` (uma vez só; refaça se a sessão expirar).

1. Dê **dois cliques em `LOGIN_MERCADOLIVRE.bat`**.
2. Abre um Chrome **separado do seu**. Faça login na sua **conta de afiliado** (senha, código de verificação etc.).
3. Confira que a página do **Linkbuilder** aparece logada, com a sua etiqueta.
4. **Feche o Chrome.** Deve aparecer `✅ Perfil salvo em ...\data\ml_profile`.

> A etiqueta do `.env` (`ML_ETIQUETA`) precisa ser **da mesma conta** em que você fez login aqui.

---

## 6. Conectar o WhatsApp do bot

1. **Abra o Docker Desktop** e espere "Engine running".
2. Adicione o **número do bot** aos grupos (como administrador).
3. Dê **dois cliques em `LOGIN_WHATSAPP.bat`**:
   - na 1ª vez ele baixa a Evolution API (~1 GB) — pode demorar;
   - gera sozinho a `EVOLUTION_API_KEY` no `.env`;
   - abre o **QR Code numa página do navegador** (ela se atualiza sozinha com o código mais recente).
4. No **celular do número do bot**: WhatsApp → **⋮ / Configurações → Aparelhos conectados → Conectar um aparelho** → leia o QR Code. (Ele vence em ~30 s; a página mostra o novo sozinha.)

> Se o WhatsApp do bot **já estiver conectado**, o login só confirma isso (espera até 30 s pela reconexão logo depois de abrir o Docker) e lista os grupos — não pede QR.
5. Aparece `✅ WhatsApp conectado!` e a **lista dos grupos** do número do bot.
6. Copie os nomes para o `whatsapp:` de cada grupo no `config.yaml` (passo 4.2).

A conexão fica salva no Docker. Só é preciso repetir se o aparelho for desconectado no celular.

Painel da Evolution (opcional, para conferir a conexão): http://localhost:8080/manager

---

## 7. Testar antes de enviar para os grupos

### 7.1 Teste na tela (sem enviar nada)
No `config.yaml`, deixe:
```yaml
destino: console
```
Dê **dois cliques em `INICIAR_BOT.bat`**. As ofertas aparecem **na tela** (e ficam salvas em `data\saida.jsonl`), com `📣 Para o grupo: ...`. Confira se aparecem links `https://meli.la/...`.

### 7.2 Teste no WhatsApp com um grupo de teste
1. Crie um grupo só com você e o número do bot.
2. No `config.yaml`, coloque o nome desse grupo de teste no `whatsapp:` dos grupos e mude para:
   ```yaml
   destino: whatsapp
   ```
3. Abra o `INICIAR_BOT.bat`. Deve aparecer `WhatsApp pronto: N grupo(s) encontrados` e as ofertas chegam no grupo com foto.

Para testes rápidos, o `config.yaml` vem com `intervalo_minutos: 1` (1 oferta por grupo por minuto).

---

## 8. Colocar para valer

No `config.yaml`:
```yaml
geral:
  intervalo_minutos: 45          # teste: 1 → produção: 30 a 60
  horario_ativo: "08:00-23:00"   # não envia de madrugada ("" = 24h)

destino: whatsapp
```
e coloque os **nomes dos grupos reais** no `whatsapp:` de cada grupo.

Avise nos grupos que os links são de afiliado (exigência dos programas). Ex.: *"Contém links de afiliado; podemos receber comissão, sem custo extra para você."*

---

## 9. Uso no dia a dia

**Ligar**
1. Abra o **Docker Desktop** (espere "Engine running").
2. Dois cliques em **`INICIAR_BOT.bat`**.

**Parar** — feche a janela. (Se apertar Ctrl+C aparece um bloco `KeyboardInterrupt` — não é erro; o Windows pergunta "Deseja finalizar o arquivo em lotes (S/N)?", responda **S**.)

**Copiar texto da janela sem parar o bot** — selecione com o mouse e aperte **Enter** (não Ctrl+C).

**O bot caiu?** O `INICIAR_BOT.bat` reinicia sozinho após 15 segundos.

**Deixar o PC ligado**
- Configurações → Sistema → Energia → *Suspender: Nunca*.
- **Início automático** (recomendado): dois cliques em **`ATIVAR_INICIO_AUTOMATICO.bat`** (uma vez). O bot passa a abrir sozinho **ao entrar no Windows e sempre que a internet conectar** (inclusive ao voltar da suspensão). Para desligar: `DESATIVAR_INICIO_AUTOMATICO.bat`.
  - No Docker Desktop, ative *Settings → General → **Start Docker Desktop when you sign in*** — sem o Docker, o WhatsApp não funciona (o bot fica tentando a cada 15 s até ele abrir).
  - O bot só roda **um por vez**: se já estiver aberto, a nova janela avisa *"O bot já está rodando em outra janela"* e fecha sozinha — sem ofertas em dobro.
  - Funciona com o seu usuário logado no Windows (na tela de senha, ele espera você entrar).
  - Para conferir/editar: menu Iniciar → *Agendador de Tarefas* → tarefa **"Bot de Ofertas - inicio automatico"**.

**Arquivos úteis**
| Arquivo | O que é |
|---|---|
| `data\saida.jsonl` | ofertas mostradas no modo `console` |
| `data\ofertas.db` | histórico de envios (controle de repetição) |
| `data\ml_profile\` | login de afiliado do Mercado Livre |
| `data\whatsapp_qr.html` | página com o último QR Code gerado |

---

## 10. Atualizar o projeto

1. **Antes**, copie o seu `config.yaml` para outro lugar (ex.: `config-backup.yaml` na Área de Trabalho) — a atualização **substitui** esse arquivo.
2. Baixe o ZIP de novo (**Code → Download ZIP**) e extraia **por cima** da pasta.
3. Reabra o `config.yaml` e recoloque seus ajustes (grupos, `whatsapp:`, `destino`, intervalos).

O `.env` e a pasta `data\` **não** são afetados (não fazem parte do ZIP).

---

## 11. Referência do `config.yaml`

### `geral`
| Chave | Padrão | O que faz |
|---|---|---|
| `intervalo_minutos` | 1 (teste) | tempo entre ciclos; produção: 30–60 |
| `max_posts_por_ciclo` | 1 | ofertas enviadas **por grupo** a cada ciclo |
| `espacamento_segundos` | 15 | pausa entre um envio e outro (inclusive entre grupos) |
| `nao_repetir_dias` | 7 | não reenviar o mesmo produto ao mesmo grupo nesse prazo |
| `horario_ativo` | `""` | ex.: `"08:00-23:00"`; vazio = 24 horas |

### `filtros`
| Chave | Padrão | O que faz |
|---|---|---|
| `desconto_minimo` | 25 | % mínimo de desconto |
| `preco_minimo` / `preco_maximo` | 0 | faixa de preço (0 = sem limite) |
| `palavras_bloqueadas` | `[]` | ignora títulos com essas palavras, ex.: `[capinha, película]` |

### `fontes.mercadolivre`
| Chave | Padrão | O que faz |
|---|---|---|
| `modo` | `auto` | `auto` = mais vendidos + página de ofertas; `api` = só API; `pagina` = só página de ofertas |
| `limite_destaques` | 20 | mais vendidos lidos por (sub)categoria |
| `subcategorias_por_busca` | 2 | (sub)categorias consultadas por ciclo, em rodízio |
| `paginas_ofertas` | 1 | páginas de ofertas lidas por ciclo (~48 promoções cada) |
| `paginas_ofertas_max` | 10 | rodízio vai da página 1 até esta e recomeça |

### `grupos` e `destino`
Veja o passo [4.2](#42-configurar-os-grupos-no-configyaml). `destino`: `console` (só tela) ou `whatsapp`.

---

## 12. Comandos (terminal)

Os `.bat` fazem tudo com dois cliques. Se preferir o PowerShell, dentro da pasta do projeto:

| Comando | O que faz |
|---|---|
| `uv run python -m ofertas check` | mostra o que falta configurar |
| `uv run python -m ofertas diagnostico` | testa quais caminhos da API do ML funcionam |
| `uv run python -m ofertas testar --mensagem` | busca e mostra ofertas de cada grupo (não envia) |
| `uv run python -m ofertas converter "<link>"` | gera o link de afiliado de um produto |
| `uv run python -m ofertas ml-login` | login de afiliado (= `LOGIN_MERCADOLIVRE.bat`) |
| `uv run python -m ofertas whatsapp-login` | conecta o WhatsApp (= `LOGIN_WHATSAPP.bat`) |
| `uv run python -m ofertas whatsapp-grupos` | lista os grupos do número do bot |
| `uv run python -m ofertas ciclo` | roda um único ciclo |
| `uv run python -m ofertas run` | roda em loop (= `INICIAR_BOT.bat`) |
| `uv run python -m ofertas run --grupo bebe` | roda só um grupo (chave do `config.yaml`) |

---

## 13. Erros e o que fazer

Procure pela **mensagem que apareceu na tela** (ou parte dela).

### 13.1 Instalação / Windows

| Mensagem | Causa | O que fazer |
|---|---|---|
| `uv : O termo 'uv' não é reconhecido...` | o uv não está instalado ou o PowerShell não o encontra | use o `BUSCAR_OFERTAS.bat` (instala sozinho), ou `winget install astral-sh.uv`, **feche e reabra** o PowerShell |
| `Failed to spawn: python` / "Uma política de Controle de Aplicativo bloqueou este arquivo" | Smart App Control do Windows 11 bloqueia o Python | tecla Windows → "Controle inteligente de aplicativos" → **Desativado** → reinicie o PC (o antivírus continua ativo) |
| `Não consegui instalar o uv` (no .bat) | falhou o download/instalação | feche a janela e abra o `.bat` de novo; confira a internet |
| `Algo deu errado ao preparar o ambiente` | falha no `uv sync` | veja a mensagem acima dela; em geral é internet ou o Smart App Control |
| Arquivo `.env` não aparece na pasta | arquivos que começam com ponto ficam ocultos | abra com `notepad .env` no PowerShell dentro da pasta |

### 13.2 API do Mercado Livre (busca de ofertas)

| Mensagem | Causa | O que fazer |
|---|---|---|
| `Sem credenciais: preencha ML_CLIENT_ID e ML_CLIENT_SECRET no .env` | `.env` sem as chaves (ou no lugar errado) | preencha o `.env` na **pasta principal** do projeto (passo 4.1) |
| `Falha ao gerar token (HTTP 400/401...)` | App ID ou Secret Key errados | copie de novo do DevCenter, sem espaços/aspas |
| `busca da API bloqueada (403) para este app — usando mais vendidos/catálogo` | o ML bloqueia a busca para a maioria dos apps | **não é erro** — o bot usa os caminhos alternativos sozinho |
| `Página de ofertas ...: 403` ou erro de conexão | o site do ML recusou/limitou o acesso | temporário: o bot continua com os mais vendidos; se persistir, aumente o `intervalo_minutos` |
| `Página de ofertas do ML mudou de layout? N cards, 0 lidos` | o ML mudou o visual da página | os mais vendidos continuam funcionando; é preciso ajustar o código (`ofertas/sources/ml_pagina.py`) |
| `Nenhuma oferta nova que passe nos filtros` / `nenhuma oferta nova nas categorias do grupo` | já enviou tudo o que havia com desconto suficiente | normal em testes de 1 minuto; aumente o intervalo, adicione categorias ao grupo ou reduza o `desconto_minimo` |
| `Mercado Livre: 0 ofertas coletadas` | todas as fontes falharam | veja as linhas de erro acima dela; rode `uv run python -m ofertas diagnostico` |

### 13.3 Link de afiliado

Sempre que o link não puder ser gerado, aparece `Linkbuilder ML falhou (link de afiliado não gerado): <motivo>` — o motivo diz o que fazer:

| Motivo | Causa | O que fazer |
|---|---|---|
| `Sessão do ML não encontrada` | o login de afiliado não foi feito **nesta pasta** | rode o `LOGIN_MERCADOLIVRE.bat` (passo 5) na mesma pasta do `INICIAR_BOT.bat` |
| `Sessão do ML expirou` | o login venceu | rode o `LOGIN_MERCADOLIVRE.bat` de novo |
| `ML_ETIQUETA não configurada no .env` | faltou a etiqueta | preencha `ML_ETIQUETA` (passo 4.1) |
| `Tag is not associated with this affiliate` (error_code 109) | a etiqueta do `.env` não é da conta logada | copie a "Etiqueta em uso" do Linkbuilder **da mesma conta**; se o login foi em outra conta, apague `data\ml_profile` e refaça o login |
| `createLink respondeu HTTP ...` / `createLink devolveu 0 links` | o ML recusou a geração | refaça o login; se persistir, anote a mensagem completa para análise |
| `Google Chrome não encontrado` | Chrome não instalado | instale o Google Chrome |
| `Executable doesn't exist` | sem Chrome e sem o Chromium do projeto | instale o Google Chrome (recomendado) ou rode `uv run python -m ofertas instalar-navegador` |

Relacionadas:
- `Sem link de afiliado, descartada: ...` — a oferta foi descartada (regra: **nunca** envia sem link de afiliado). O bot tenta a próxima melhor no lugar.
- `nenhuma oferta enviada: não foi possível gerar link de afiliado` — nenhuma candidata conseguiu link; resolva o motivo da linha `Linkbuilder ML falhou`.

### 13.4 WhatsApp (Evolution API)

| Mensagem | Causa | O que fazer |
|---|---|---|
| `Docker não encontrado — instale o Docker Desktop` | Docker não instalado | instale o Docker Desktop (passo 3.4) |
| `docker compose falhou — o Docker Desktop está aberto?` | Docker Desktop fechado ou ainda iniciando | abra o Docker Desktop, espere "Engine running" e tente de novo |
| `A Evolution API não respondeu em http://localhost:8080 após 120s` | a Evolution demorou para subir (comum na 1ª vez) ou falhou | espere e tente de novo; no Docker Desktop veja se os containers `bot-ofertas-evolution` estão "Running" |
| `Evolution API fora do ar (http://localhost:8080)` | a Evolution parou durante o uso | abra o Docker Desktop; o bot sobe a Evolution de novo ao reiniciar |
| `A Evolution API não conseguiu gerar o QR Code` | a Evolution não alcança os servidores do WhatsApp | confira internet, antivírus/firewall/VPN; rode o `LOGIN_WHATSAPP.bat` de novo |
| `Tempo esgotado sem ler o QR Code` | o QR não foi lido em 3 minutos | rode o `LOGIN_WHATSAPP.bat` de novo e leia com o celular **do número do bot** |
| `WhatsApp do bot não está conectado (estado: close/connecting)` | aparelho desconectado no celular (ou nunca conectado). O bot já espera até 45 s pela reconexão automática antes de dar esse erro | confira no celular do bot em *Aparelhos conectados*; rode o `LOGIN_WHATSAPP.bat` |
| `Não consegui gravar o QR Code em ...` | o arquivo da página do QR não pôde ser gravado | o login continua tentando; se persistir, feche a página do QR e rode o login de novo, ou conecte pelo painel http://localhost:8080/manager (login com a `EVOLUTION_API_KEY` do `.env`) |
| `O grupo 'xxx' não tem 'whatsapp:' no config.yaml` | faltou o nome do grupo | preencha `whatsapp:` desse grupo (passo 4.2) |
| `Grupo 'xxx' não encontrado no WhatsApp do bot` | nome diferente do real, ou o número do bot não está no grupo | rode `uv run python -m ofertas whatsapp-grupos` e copie o nome **exato**; adicione o número do bot ao grupo |
| `foto recusada (...) — enviando só o texto` | o WhatsApp não aceitou a imagem | não é grave: a oferta vai só com texto e a prévia do link |
| `falha ao enviar '...': ... HTTP 400/500` | a Evolution não conseguiu enviar (desconexão, bloqueio temporário) | a oferta **não** é marcada como enviada e volta num próximo ciclo; se repetir, confira a conexão (`LOGIN_WHATSAPP.bat`) |
| O número do bot foi **bloqueado** pelo WhatsApp | envio automatizado detectado | use outro número, aumente o `intervalo_minutos` e o `espacamento_segundos`, envie para menos grupos |

> O `INICIAR_BOT.bat` reinicia sozinho em 15 s se o bot parar por um desses erros. Enquanto a causa não for resolvida, ele vai repetir a mensagem — feche a janela, corrija e abra de novo.

### 13.5 Docker

| Mensagem | Causa | O que fazer |
|---|---|---|
| `Docker Desktop failed to start because virtualisation support wasn't detected` | virtualização desligada no PC | veja abaixo |
| `WSL ...` / "WSL 2 installation is incomplete" | WSL não instalado | PowerShell **como administrador**: `wsl --install` → reinicie o PC |
| `docker version` mostra só "Client" + `error during connect` | Docker Desktop fechado ou iniciando | abra o Docker Desktop e espere "Engine running" |

**Ligar a virtualização**
1. Gerenciador de Tarefas (Ctrl+Shift+Esc) → **Desempenho → CPU** → veja "Virtualização".
2. Se estiver **Desabilitado**: Configurações → Sistema → Recuperação → **Inicialização avançada → Reiniciar agora** → Solução de problemas → Opções avançadas → **Configurações de Firmware UEFI** → Reiniciar.
3. Na BIOS, ative **Intel Virtualization Technology / VT-x** (Intel) ou **SVM Mode / AMD-V** (AMD) → salve (geralmente F10).
4. Rode `wsl --install` (PowerShell como administrador) e reinicie.

Em computador de empresa, a BIOS pode estar bloqueada — só o suporte de TI libera.

### 13.6 Configuração (`config.yaml`)

| Mensagem | Causa | O que fazer |
|---|---|---|
| `Nenhum grupo no config.yaml` | seção `grupos` vazia ou grupos sem `categorias` | confira o passo 4.2 |
| `Grupo não encontrado no config.yaml: xxx` | `--grupo` com chave que não existe | use a chave exata do grupo (ex.: `casa_info`) |
| `Destino desconhecido no config.yaml` | `destino` escrito errado | use `console` ou `whatsapp` |
| Erro com `yaml` / `ScannerError` / `mapping values are not allowed` | formatação do arquivo quebrada | use espaços (não TAB), mantenha o alinhamento, e coloque aspas em nomes com `:` ou `#` |
| `Fora do horário ativo (...) — ciclo pulado` | fora da janela de `horario_ativo` | não é erro; ajuste `horario_ativo` se quiser outro horário |

| `ATIVAR_INICIO_AUTOMATICO.bat` mostra erro em vermelho | o Windows bloqueou a criação da tarefa agendada | clique com o botão direito no `.bat` → **Executar como administrador**; se persistir, envie um print da janela |

### 13.7 Mensagens que **não** são erro
- `O bot já está rodando em outra janela — esta vai fechar.` — o início automático (ou você) tentou abrir um segundo bot; o primeiro continua funcionando.
- `KeyboardInterrupt` — você apertou Ctrl+C (o bot foi parado).
- `busca da API bloqueada (403) ... usando mais vendidos/catálogo` — caminho alternativo automático.
- `Sem link de afiliado, descartada` — regra de segurança da comissão.
- `Fora do horário ativo` — respeitando o horário configurado.

---

## 14. Segurança e uso responsável

- **Nunca compartilhe** o `.env` nem a pasta `data\` (senhas, login de afiliado, histórico).
- **Número do bot separado** do seu pessoal; ritmo moderado (30–60 min por grupo) para reduzir o risco de bloqueio. Automatizar o WhatsApp não é permitido pelos termos do WhatsApp.
- **Aviso de afiliado** na descrição dos grupos.
- Os preços mudam a qualquer momento; a mensagem mostra o preço do momento da coleta.
- **Backup**: guarde uma cópia do `.env` e do `config.yaml` em lugar seguro.
