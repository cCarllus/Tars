# 008_LEVELS_XP_SYSTEM_FEATURE_SPEC.md

## Objective

Implementar um sistema completo, moderno e altamente configurável de **XP e Níveis** no TARS, inspirado no MEE6 mas superior (com suporte a voz, tickets, tribunal e integração futura com economia).

O sistema deve recompensar atividade real, dar sensação de progressão e ser totalmente gerenciável via Dashboard.

## Context

- Melhorar o engajamento dos membros.
- Preparar base para integração com Economia (T-Coins) e Minecraft.
- Substituir qualquer sistema antigo de XP (MEE6 ou similar).

## Domain / Package

**Domain:** Progression System  
**Package:** `bot/cogs/levels/`, `bot/services/`, `bot/database/models/`, `dashboard/`

**Principais arquivos a criar:**

- `bot/cogs/levels/levels_cog.py`
- `bot/services/xp_service.py`
- `bot/database/models/level_models.py`
- `bot/utils/xp_utils.py`
- Atualizações na Dashboard (`dashboard/routes/levels.py`, templates)

## Features Principais

### 1. Ganho de XP

- **Mensagens**: 15-25 XP por mensagem (cooldown de 60 segundos anti-spam).
- **Voz**: 20-30 XP por minuto em canal de voz (bônus +50% se 2+ pessoas na call).
- **Daily**: Comando `/daily` com streak bonus (aumenta até 7 dias).
- **Tickets**: Recompensa ao criar ticket aceito e ao fechar como condutor.
- **Tribunal**: Recompensa para juízes e participantes (baseado em participação).
- **Outros**: Configurável (participação em eventos, etc.).

### 2. Sistema de Níveis

- Fórmula de XP necessária: `5 * (level ** 2) + 50 * level + 100` (mesma do MEE6, mas configurável).
- Anúncio bonito quando o usuário sobe de nível (embed com rank card simples).
- Cargos automáticos por nível (role rewards) configuráveis na Dashboard.

### 3. Comandos

- `/rank` → Mostra card de rank do usuário (XP, nível, posição no leaderboard).
- `/leaderboard` → Top 10 (global e semanal).
- `/daily`
- Comandos admin: `/xp add @user amount`, `/xp set @user level`, etc.

### 4. Anti-Abuso

- Cooldowns por atividade.
- Ignorar bots, canais configurados (ex: #bot-commands).
- Detecção básica de spam (mensagens repetidas).

### 5. Dashboard

- Configurar:
  - Taxas de XP por atividade.
  - Canais ignorados.
  - Cargos por nível.
  - Fórmula de nível.
  - Mensagem de level up.
- Visualizar leaderboard e estatísticas.

### 6. Preparação para Integração

- Models preparados para futura Economia (T-Coins).
- API endpoints básicos já inclusos (ver spec futura).

## Technical Details

- **Banco de Dados**:
  - Tabela `user_levels` (user_id, xp, level, messages_count, voice_minutes, daily_streak, last_daily, etc.)
  - Tabela `level_rewards` (level, role_id)

- **Eventos**:
  - `on_message`
  - `on_voice_state_update`

- **Cálculo de Nível**:
  - Função para calcular nível a partir de XP total.
  - Função para XP necessário para próximo nível.

## Acceptance Criteria

- Sistema de ganho de XP funcionando para mensagens e voz.
- `/rank` e `/leaderboard` bonitos.
- Level up announcement funcional.
- Tudo configurável via Dashboard.
- Código limpo, com type hints, docstrings e seguindo AGENTS.md.
- Testes unitários para ganho de XP e cálculo de níveis.

## Implementation Order (Recomendado)

1. Models do banco + XP Service
2. Cog básico (ganho por mensagem e voz)
3. Comandos (/rank, /daily, /leaderboard)
4. Dashboard
5. Integrações com Tickets/Tribunal
6. Anúncios de level up + role rewards

## Next Steps

Após aprovação desta spec, implementar o código.
Em seguida, criar a spec 009 para o sistema de Economia (T-Coins) integrado.
