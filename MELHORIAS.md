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

## 2. Outras propostas pendentes
- **Log com o motivo do descarte**: "40 por palavra bloqueada, 10 por desconto baixo, 5 já enviadas" — mostra na hora por que uma categoria não rende.
- **Erro de grupo não encontrado listando os grupos que o bot enxerga** — evita rodar outro comando para achar o nome certo.
- **Botão "Iniciar bot" no painel.**
