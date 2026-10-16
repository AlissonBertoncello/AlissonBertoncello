# Melhorias em análise (não implementadas)

Ideias levantadas a partir de grupos concorrentes. **Nada aqui foi implementado** — cada item depende de aprovação.

---

## 1. Mensagem: aprendizados de um grupo concorrente (15/10/2026)

Mensagens analisadas:

```
SOM DE RESPEITO SEM PRECISAR VENDER UM RIM!

Rádio Pioneer MVH-145BR Bluetooth 5.4

De R$ 339 por R$ 281 no Pix
🎟️ Use o Cupom: APROVEITA

https://meli.la/...
```
```
QUEM GOSTA DE MOTOR, GOSTA DE OUVIR ELE RESPIRAR

Filtro de Ar Esportivo Duplo Fluxo Universal RaceChrome

Por R$ 133 em 4x

https://meli.la/...
```

### O que eles fazem
| Elemento | Exemplo | Efeito |
|---|---|---|
| Gancho em CAIXA ALTA, com humor, na linguagem do nicho | "SOM DE RESPEITO SEM PRECISAR VENDER UM RIM!" | para a rolagem; parece gente do grupo, não robô |
| Nome do produto curto | "Rádio Pioneer MVH-145BR Bluetooth 5.4" | nome limpo, não o título enorme do anúncio |
| Preço direto, arredondado | "De R$ 339 por R$ 281 no Pix" | sem centavos, sem excesso de emoji |
| Gatilho extra | cupom ("APROVEITA"), parcelamento ("em 4x") | pesa mais que o % de desconto |
| Posta mesmo sem desconto | filtro de ar só com "Por R$ 133 em 4x" | relevância para o público > desconto |
| Mensagem curta | ~5 linhas | lida em 2 segundos |
| Números diferentes em rodízio | 9802-5772 e 9802-2234 | divide o volume e o risco de bloqueio; permite postar a cada ~7 min |

### Propostas
| # | Mudança | Custo | Esforço |
|---|---|---|---|
| 1 | **Gancho por grupo**: lista de frases de abertura por grupo, editável no painel, em rodízio | grátis | pequeno |
| 2 | **Gancho escrito por IA** (Claude) para cada produto | pago por uso (baixo); precisa de chave da API da Anthropic | médio |
| 3 | **Título curto**: 6–8 palavras principais, sem repetições | grátis | pequeno |
| 4 | **Parcelamento e cupom** quando a página de ofertas do ML mostrar (conferir em `data\ml_ofertas_debug.html`) | grátis | médio |
| 5 | **Formato enxuto**: preço sem centavos quando redondo, menos emojis, rodapé de convite em 1 linha | grátis | pequeno |
| 6 | **Vários números de WhatsApp em rodízio** (Evolution suporta várias instâncias) | 1 chip a mais | maior |

Recomendação: começar por **1, 3 e 5**; depois de 1–2 semanas medindo entradas/saídas, testar a **2**; a **6** só se quiser chegar perto de 1 post a cada 5 min.

Exemplo com 1 + 3 + 5:
```
*SOM DE RESPEITO SEM PRECISAR VENDER UM RIM!* 🔊

Rádio Pioneer MVH-145BR Bluetooth
De ~R$ 339~ por *R$ 281* no Pix (-17%)

🛒 https://meli.la/...
👉 Chama a galera: https://chat.whatsapp.com/...
```

---

## 2. Análise completa do grupo "O Guru dos Carros" (14/10 16h → 16/10 11h)

Base: exportação da conversa, **160 postagens com link** (154 ofertas + 6 avisos de cupom), em ~1,5 dia.

### Ritmo
- **Intervalo mediano: 6,4 min** (média 8,4; mínimo 4; máximo 30) → ~9 posts por hora, ~90 por dia.
- **Horário:** das 9h às 23h. Mais forte das **16h às 23h** (14–16 posts/hora); mais fraco das 11h às 15h (4–8/hora).
- **3 números em rodízio, quase em partes iguais:** 61 / 56 / 43 posts. É isso que permite o ritmo sem bloqueio.

### Mix de categorias (154 ofertas)
| Categoria | % |
|---|---|
| Limpeza e estética automotiva (Vonixx, shampoo, cera, snow foam, microfibra, aspirador) | **34%** |
| Ferramentas (parafusadeira, chave de impacto, jogos de chaves) | 16% |
| Manutenção (óleo, pneus, filtro, palheta, lâmpada, macaco, compressor) | 14% |
| Lifestyle masculino (perfume, relógio, camisetas, meias, creatina) | 8% |
| Acessórios (tapete, capa, suporte de celular, aromatizante, organizador) | 8% |
| Som e multimídia (rádio, alto-falante, sub, CarPlay) | 7% |
| Moto (capacete, comunicador, capa) | 5% |
| Segurança (alarme, trava, rastreador, câmera de ré) | 4% |
| Eletrônicos e casa (power bank, cabo, projetor) | 3% |

### Sequência
- **Quase nunca repetem a categoria em seguida:** 111 de 132 trechos têm 1 post só; no máximo 5 seguidos.
- **"Limpeza" é a âncora:** aparece a cada 2 ou 3 posts. As outras categorias se intercalam entre elas.
- **Lifestyle masculino entra a cada ~10 posts** para quebrar o ritmo (perfume, relógio), sempre ligado ao público ("PERFEITO PRA SAIR COM A MORENA").
- **Cupons gerais do ML/Shopee ~3 vezes por dia** ("NOVOS CUPONS MERCADO LIVRE" + código + link da lista).

### Preço e formato
- **Preço mediano R$ 73**; 66% custam até R$ 120 (compra por impulso). Só 10% passam de R$ 250.
- **70% mostram "De / Por"**; 30% só "Por R$ X" (sem desconto aparente).
- **31% com cupom**, 28% "no Pix", 10% parcelado.
- **98% dos ganchos em CAIXA ALTA**; 9% em forma de pergunta; linguagem do público ("nave", "morena", "patrão", "pila").
- **Lojas:** Mercado Livre 76%, Shopee 22%, Amazon 1%.

### Repostam os campeões
O mesmo produto volta em menos de 24 h com outro gancho, muitas vezes com urgência: Kit Vonixx 3x, chave de impacto Kinetx 2x, mini compressor 2x ("BAIXOU DE PREÇO DE NOVO", "NESSE PREÇO POR MAIS 1h15!"), mangueira com snow foam 2x, flanelas 2x. O nosso bot bloqueia repetição por 7 dias (`nao_repetir_dias`).

### Propostas a partir dessa análise
| # | Proposta | Tipo |
|---|---|---|
| 7 | **Peso por categoria** (ex.: limpeza automotiva 3×, ferramentas 2×, as outras 1×) para imitar o mix, em vez do rodízio igual | código |
| 8 | **Proporção ML / Shopee configurável** por grupo (ex.: 3 ML : 1 Shopee), em vez de meio a meio | código |
| 9 | **Repostar campeões:** permitir repetir um produto depois de 1–2 dias com outro gancho ("BAIXOU DE NOVO") | código + config |
| 10 | **Horário com ritmo variável:** mais posts das 16h às 23h, menos no começo da tarde | código |
| 11 | **Post de cupons gerais** 2–3 vezes por dia (os cupons do ML não vêm pela API: seria uma lista mantida no painel) | código |
| 12 | **Confraria focada em carro:** categorias e palavras da Shopee na proporção acima, + lifestyle masculino como tempero | config (painel) |

---

## 3. Outras propostas pendentes
- **Log com o motivo do descarte**: "40 por palavra bloqueada, 10 por desconto baixo, 5 já enviadas" — mostra na hora por que uma categoria não rende.
- **Erro de grupo não encontrado listando os grupos que o bot enxerga** — evita rodar outro comando para achar o nome certo.
- **Botão "Iniciar bot" no painel.**
