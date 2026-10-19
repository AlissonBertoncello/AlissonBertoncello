# Briefing — Grupos de ofertas no WhatsApp → etapa de tráfego pago

> Cole este texto inteiro numa conversa nova com o Claude. Os campos entre **[colchetes]** são para você completar antes (números atuais, orçamento etc.).

---

## 1. Quem sou e o que eu quero agora
Tenho um negócio de **grupos de ofertas no WhatsApp com links de afiliado** (Mercado Livre e Shopee). A parte técnica está pronta e rodando sozinha: um bot posta ofertas nos grupos o dia todo. **Agora quero crescer os grupos com tráfego pago**, de forma lucrativa e sem queimar dinheiro. Preciso de ajuda para montar e conduzir essa etapa.

## 2. Modelo de negócio
- Ganho **comissão de afiliado** quando alguém compra pelos meus links (Mercado Livre Afiliados e Shopee Afiliados).
- Receita ≈ **membros nos grupos × % que compra × ticket médio × % de comissão**.
- Comissões que já recebi até hoje: **[preencher: R$ … / ainda nenhuma]**.
- % de comissão média por loja/categoria: **[preencher, se souber — senão, me ajude a estimar]**.
- Amazon: ainda não uso (a conta de Associados ainda não tem vendas aprovadas).

## 3. Os grupos (3 nichos)

| Grupo (nome no WhatsApp) | Público | O que posta | Membros hoje |
|---|---|---|---|
| **Achadinhos da Gabi 💄** | mulheres | beleza, skincare, maquiagem, perfumes, cabelo, moda (vestidos, blusas, leggings, fitness feminino), acessórios | **[preencher]** |
| **Achadinhos Mamãe e Bebê 🍼** | mães e gestantes | fraldas, higiene, banho, alimentação/amamentação, quarto, passeio, segurança, roupas de bebê, brinquedos | **[preencher]** |
| **Confraria do Desconto 🚗🔧** | homens que curtem carro/moto/ferramenta | limpeza e estética automotiva (âncora), ferramentas, manutenção (óleo, pneu, palheta), acessórios, som, moto, e um pouco de lifestyle masculino (perfume, relógio, tênis, suplementos) | **[preencher]** |

- Cada grupo tem **link de convite** próprio (vai no rodapé de toda oferta, para indicação).
- WhatsApp limita cada grupo a ~1.000 membros: o bot já suporta **vários grupos recebendo as mesmas ofertas** (grupo 2, 3…) quando lotar.
- Grupos configurados como **"só admins enviam"** (só oferta, sem conversa). Descrição do grupo já tem aviso de link de afiliado.
- **Prioridade sugerida até aqui:** começar a divulgação pelo **Mamãe e Bebê** (compra recorrente — fralda, lenço; mães indicam muito umas às outras; Black Friday e Natal chegando), depois **Gabi** (maior público, mais concorrido) e **Confraria** (nicho masculino, inspirado no concorrente abaixo).

## 4. Como o bot funciona (o "produto" que o tráfego vai vender)
- Posta **1 oferta por grupo a cada 10 minutos**, das 8h às 23h (~90 ofertas/dia por grupo), alternando Mercado Livre e Shopee (proporção configurável por grupo, ex.: 3 ML : 1 Shopee).
- Só posta com **desconto mínimo de 10%**, sem repetir o mesmo produto por 7 dias, com filtro de palavras por grupo (tira itens fora do tema).
- **Todo link é de afiliado** (oferta sem link de afiliado é descartada).
- Formato da mensagem (foto do produto + legenda):
  ```
  *SUA NAVE MERECE ESSE CUIDADO 🚗*            ← gancho em caixa alta (rodízio de ~15 por grupo)

  Kit Cera De Carnauba Tok Final Vonixx 500ml   ← título curto
  De ~R$ 98~ por *R$ 59* 🔻40%
  💰 Você economiza *R$ 39*
  🚚 Frete grátis

  *🛒 Garante o seu no Mercado Livre:*          ← chamada de compra do grupo
  https://meli.la/...

  🤝 Manda pro parceiro que tá precisando!      ← chamada de indicação do grupo
  👉 https://chat.whatsapp.com/...              ← convite do grupo
  ```
- Roda num notebook (Windows) com WhatsApp conectado via Evolution API, **um único número** de WhatsApp.
- Tenho um painel local para mudar categorias, ritmo, textos etc. sem mexer em código.

## 5. Referência de concorrente ("O Guru dos Carros", analisado em 160 postagens)
- Ritmo: **1 oferta a cada ~6–7 min** (~90/dia), forte das 16h às 23h. Usa **3 números de WhatsApp em rodízio** (dilui o risco de bloqueio).
- Mix: 34% limpeza automotiva (âncora), 16% ferramentas, 14% manutenção, 8% lifestyle masculino, 8% acessórios, 7% som, 5% moto…
- Preço mediano **R$ 73** (66% até R$ 120 → compra por impulso); 70% mostram "De/Por"; 31% com cupom.
- Ganchos em CAIXA ALTA com a linguagem do público ("nave", "patrão", "morena"); repostam campeões de venda com urgência ("BAIXOU DE NOVO"); postam cupons gerais do ML ~3×/dia.

## 6. O que já está planejado (plano orgânico + primeira ideia de pago)
- **Orgânico:** Status do WhatsApp diário, perfis de Instagram/TikTok por grupo (1 reel/dia + stories com achados), parcerias com grupos de mães/bairro/condomínio e micro-influenciadoras.
- **Links rastreáveis (Bitly) por canal**, ex.: `bit.ly/bebe-ads-a`, `bit.ly/bebe-insta`, `bit.ly/bebe-indica` — para saber de onde vem cada entrada.
- **Primeira ideia de pago (Meta Ads — Instagram/Facebook):**
  - Objetivo Tráfego → destino: link curto → convite do grupo. Reels + Stories, vertical 9:16.
  - **R$ 20/dia por grupo por 7 dias** (teste), 3 criativos por grupo.
  - Criativos-base: (A) oferta real "De R$ 149 por R$ 69 — ofertas assim todo dia no WhatsApp"; (B) dor ("Mãe, você está pagando caro em fralda?"); (C) data/lista ("3 achadinhos abaixo de R$ 50").
  - **Regras de decisão:** custo por entrada **≤ R$ 1,00** = manter e escalar; R$ 1–2 = trocar criativo; **> R$ 2,00** = pausar. Muitas saídas em 48 h = promessa do anúncio está atraindo curiosos.
- **Metas iniciais por grupo:** 100–200 membros em 2 semanas; 300–500 em 30 dias; **800–1.000 até a Black Friday** (abrir "grupo 2" se lotar).

## 7. Calendário
- Hoje: **[data]**. **Black Friday: 27/11/2026** (maior oportunidade do ano — ideia: "Lista VIP Black Friday" no WhatsApp). Depois: **Natal** (brinquedos, presentes de beleza, ferramentas).

## 8. Restrições e riscos
- **Um número de WhatsApp só** e API não oficial: crescer muito rápido ou postar demais aumenta o risco de bloqueio. (Possível evolução: 2–3 números em rodízio.)
- O WhatsApp não mostra de onde veio cada membro: a medição depende dos **links Bitly por canal** + contagem manual de membros.
- Não quero comprar listas nem adicionar pessoas sem consentimento.
- Anúncios precisam respeitar as políticas da Meta e dos programas de afiliados (sem promessas enganosas; deixar claro que são links de afiliado).
- Orçamento disponível para tráfego: **[preencher: R$ … por mês]**. Região: **[Brasil todo / meu estado / minha cidade]**.
- Já tenho: **[Instagram/TikTok dos grupos? conta de anúncios da Meta? cartão cadastrado? Bitly?]**.

## 9. O que eu quero de você (Claude)
1. **Plano de tráfego pago** para as próximas 6 semanas (até a Black Friday): qual grupo primeiro, canais (Meta Ads, TikTok Ads, Google?), orçamento por semana, e quando escalar ou cortar.
2. **Conta de viabilidade:** quanto posso pagar por membro (CPA máximo) para dar lucro, com base em comissão, ticket médio e taxa de compra — se eu não tiver os números, use estimativas conservadoras e me diga como medir os reais.
3. **Públicos e segmentação** para cada grupo (interesses, idade, região, lookalike quando tiver base).
4. **Criativos:** roteiros de 15–30 s para Reels/TikTok, textos de anúncio e chamadas — 5 por grupo, no tom de cada público.
5. **Destino do anúncio:** link direto do convite ou uma página intermediária simples (com aviso de afiliado e botão "entrar no grupo")? Prós e contras.
6. **Medição:** como montar os links rastreáveis e uma planilha semanal simples (entradas, saídas, custo por membro, cliques/vendas de afiliado).
7. **Retenção:** como evitar que quem entra pelo anúncio saia logo (mensagem de boas-vindas, frequência, ofertas âncora).
8. **Plano da Black Friday:** "Lista VIP", aquecimento, cronograma de verba e mensagens.

Responda em português, com passos práticos que eu consiga executar sozinho, e me pergunte o que faltar.
