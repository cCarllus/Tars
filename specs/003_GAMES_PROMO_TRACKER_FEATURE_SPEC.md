# GAMES_PROMO_TRACKER_FEATURE_SPEC.md

## Nome Oficial da Feature

Games Promo Tracker

## Objetivo

Criar um sistema inteligente de promoções de jogos que combina CheapShark + IsThereAnyDeal para entregar as melhores ofertas (Epic + Steam + outras lojas) de forma automática e via comando.

## Canal Dedicado

ID: 1498085291506794549
Nome sugerido: #・promocoes

O bot só deve postar automaticamente e aceitar o comando neste canal.

## Comando

/games promo

- Funciona apenas no canal acima
- Retorna um resumo visual das melhores promoções do momento

## Fontes de Dados

1. CheapShark API → Deals rápidos, Steam, descontos altos
2. IsThereAnyDeal (ITAD) API → Dados ricos, Epic Free Games, Historical Low, bundles

## Credenciais (já obtidas)

ITAD API Key: 1c491843828aac5a02aaf79ba4a60da6364f2aa2
ITAD Client ID: 50efc05b9726e30b

## Funcionalidades

**1. Modo Automático (Background Task)**

- Verifica a cada 45-60 minutos
- Posta automaticamente no canal #・promocoes quando:
  - Novos jogos grátis da Epic
  - Início de grandes sales (Summer Sale, etc.)
  - Deals com desconto ≥ 75%
  - Jogos em Historical Low

**2. Modo Manual**

- Comando: `/games promo`
- Mostra embed com:
  - Jogos grátis da Epic da semana
  - Top 6-8 melhores deals (Steam + outras lojas)
  - Informações de preço histórico (via ITAD)

## Embed Padrão

- Título: 🔥 Promoções do Momento
- Seção "🎁 Grátis na Epic" (se houver)
- Seção "🔥 Melhores Ofertas"
- Cada jogo com:
  - Imagem do jogo
  - % de desconto em destaque (verde/vermelho)
  - Preço atual / antigo
  - "Historical Low" quando aplicável
  - Tempo restante (quando disponível)
  - Botões: "Steam" | "Epic" | "Ver Oferta"

## Regras de Negócio (Obrigatórias)

1. Tudo (automático e comando) só funciona no canal 1498085291506794549
2. Se o comando for usado em outro canal → responder com erro amigável
3. Evitar duplicatas (usar cache de deals já postados)
4. Máximo 3-4 posts automáticos por dia
5. Usar safe_discord.py para todas as postagens
6. Respeitar rate limits das duas APIs
7. Logging estruturado de todas as buscas e postagens
8. Fallback: se uma API falhar, usar a outra

## Estrutura de Arquivos Recomendada

bot/cogs/games/
├── promo_tracker.py
bot/services/
├── game_deals_service.py ← Combina CheapShark + ITAD
bot/utils/
├── promo_embeds.py
├── game_deals_cache.py
bot/tasks/
├── promo_checker.py ← Background task

## Configuração via .env

PROMO_CHANNEL_ID=1498085291506794549
ITAD_API_KEY=1c491843828aac5a02aaf79ba4a60da6364f2aa2
ITAD_CLIENT_ID=50efc05b9726e30b

## Fluxo do Comando /games promo

1. Usuário executa o comando no canal correto
2. Service busca dados nas duas APIs
3. Combina e filtra os melhores deals
4. Gera embed rico
5. Responde no canal

## Fluxo Automático

1. Task roda periodicamente
2. Busca novos deals relevantes
3. Verifica cache para não repostar
4. Envia no canal via safe_discord

## Acceptance Criteria

- [ ] Comando /games promo funciona apenas no canal correto
- [ ] Usa as duas APIs (CheapShark + IsThereAnyDeal)
- [ ] Embed visual e profissional
- [ ] Sistema automático posta deals relevantes
- [ ] Não gera spam ou duplicatas
- [ ] Segue ARCHITECTURE_GUIDELINES.txt (safe calls, logging, etc.)

## Commit Sugerido

feat: implementar Games Promo Tracker com CheapShark + IsThereAnyDeal

## Observações

- Feature de alto valor para o servidor
- Fácil de expandir (wishlist, alertas por jogo, etc.)
- Manter leve para não sobrecarregar o bot
