# TARS Core Server System

## Objective

Desenvolver o sistema central completo do TARS responsável por gerenciar todas as funções essenciais do servidor, substituindo de forma definitiva o MEE6 e a Loritta. O sistema deve incluir:

- Sistema avançado de Leveling / XP / Leaderboard
- Mensagens automáticas de boas-vindas e saída via embeds personalizáveis
- Canal de Logs completo (#・tars-logs) com 3 níveis configuráveis de detalhe
- Auto-moderação inteligente
- Alertas em tempo real
- Base sólida para Dashboard Web (único local de configuração)

**Todo o sistema de configuração (canais, cargos, mensagens, níveis de log, regras de auto-mod, etc.) deve ser feito EXCLUSIVAMENTE através da Dashboard Web.** O dono do servidor (Carllos) é o único usuário autorizado a acessar e alterar qualquer configuração.

## Context

O servidor possui um grande volume de usuários e necessita de um bot único, estável, seguro e altamente configurável. Atualmente, as funções estão divididas entre MEE6 e Loritta. O TARS deve centralizar tudo em um único bot, com experiência premium para os membros e controle total e seguro para a administração. A Dashboard Web será o "cérebro" do bot, onde todas as configurações sensíveis são feitas, evitando comandos espalhados no Discord e garantindo maior segurança e organização.

## Domain / Package

**Domain:** Core Server Management & Configuration  
**Package:** `bot/cogs/core/`

**Arquivos principais:**

- `bot/cogs/core/audit_log.py`
- `bot/cogs/core/welcome_leave.py`
- `bot/cogs/core/leveling.py`
- `bot/cogs/core/auto_mod.py`
- `bot/services/core_config_service.py`
- `bot/services/leveling_service.py`
- `bot/services/welcome_service.py`
- `bot/services/audit_log_service.py`
- `bot/database/models/core_models.py`

## Inputs

- Eventos do Discord: `on_member_join`, `on_member_remove`, `on_message`, `on_voice_state_update`, `on_user_update`, `on_message_delete`
- Configurações salvas via Dashboard Web (JSON serializado no banco)
- Dados persistidos no SQLite3 (níveis de usuários, histórico de logs, configurações do servidor)
- Comandos públicos executados pelos usuários (`/level`, `/level top`)
- Dados enviados pela Dashboard Web (alterações de configuração em tempo real)

## Expected Output

- Embed de boas-vindas personalizado enviado automaticamente no canal configurado na Dashboard
- Embed de saída enviado automaticamente no canal configurado
- Registros detalhados no canal `#・tars-logs` (visível apenas para Admins) respeitando o nível de detalhe configurado
- Respostas claras dos comandos `/level` e `/level top`
- Alertas em tempo real via embeds coloridos no canal de logs e/ou DM para o dono
- Todas as configurações aplicadas imediatamente após salvar na Dashboard
- Logs completos, filtráveis e exportáveis disponíveis apenas na Dashboard Web

## Business Rules

1. **Configuração Centralizada**: 100% das configurações (canais, cargos automáticos, mensagens de welcome/leave, nível de logs, regras de auto-mod, whitelist de links, lista de palavrões, etc.) devem ser feitas **exclusivamente na Dashboard Web**.
2. **Acesso Restrito**: Apenas o dono do servidor (Carllos - ID específico) pode acessar a Dashboard Web.
3. **Canal de Logs**: Visível apenas para usuários com cargo de Administrador ou superior.
4. **Níveis de Logs**: 3 níveis configuráveis na Dashboard (Básico, Normal, Detalhado). Dashboard sempre mostra nível máximo.
5. **Cargo Automático**: Deve existir configuração na Dashboard para atribuir um cargo específico a todo novo membro que entrar.
6. **Leveling**: Não atribui cargos automáticos por nível (por enquanto). Apenas acumula XP e exibe leaderboard.
7. **Segurança**: Todas as alterações na Dashboard geram log interno auditável.
8. **Performance**: O sistema deve suportar alto volume de mensagens e eventos simultâneos sem bloquear o event loop.
9. **Persistência**: Todas as configurações e dados devem ser salvos no SQLite3 e carregados automaticamente no startup do bot.

## Main Flow

1. Dono acessa a Dashboard Web e configura:
   - Canal de boas-vindas
   - Canal de saída
   - Canal de logs
   - Cargo automático para novos membros
   - Nível de detalhe dos logs
   - Texto e cor dos embeds de welcome/leave
   - Regras de auto-moderação
2. Bot carrega todas as configurações do banco no startup
3. Novo membro entra → bot atribui cargo automático + envia embed de boas-vindas no canal configurado
4. Usuário envia mensagens ou fica em voice → ganha XP
5. Qualquer evento relevante (join, leave, nick change, etc.) é registrado no canal de logs conforme o nível configurado
6. Auto-moderação atua em segundo plano e registra todas as ações no log

## Alternative Flows / Errors

- Canal configurado na Dashboard não existe mais → Bot envia alerta crítico via DM para o dono e usa um canal de fallback
- Cargo automático configurado não existe → Bot registra erro detalhado no log interno e notifica o dono
- Nível de logs configurado como Básico → Eventos menos importantes não aparecem no canal de logs
- Dashboard offline ou com erro → Bot continua funcionando com as últimas configurações salvas no banco
- Bot sem permissão para enviar mensagem no canal de welcome/logs → Alerta crítico enviado ao dono via DM

## Classes Involved

- `CoreConfigService` — Carrega, valida e aplica todas as configurações da Dashboard
- `WelcomeService` — Gerencia embeds de boas-vindas e saída
- `AuditLogService` — Responsável por todos os logs com suporte aos 3 níveis de detalhe
- `LevelingService` — Gerencia XP, leaderboard e level up
- `AutoModService` — Executa todas as regras de moderação
- `DashboardConfigModel`, `WelcomeConfigModel`, `LogConfigModel`, `AutoRoleConfigModel` (models do banco)
- `SafeDiscord`, `QueueManager`, `LockRegistry` (utilizados em todas as ações)

## Acceptance Criteria

- [ ] Toda configuração do bot é feita exclusivamente na Dashboard Web
- [ ] Dashboard permite configurar cargo automático, canais de welcome/leave/logs, nível de detalhe dos logs, mensagens de embed, etc.
- [ ] Canal `#・tars-logs` é visível apenas para usuários com cargo de Administrador
- [ ] Sistema de logs possui exatamente 3 níveis de detalhe configuráveis
- [ ] Dashboard sempre exibe logs no nível máximo (Detalhado) com filtros e busca
- [ ] Embed de boas-vindas e saída são enviados corretamente nos canais configurados
- [ ] Cargo automático é atribuído a todo novo membro
- [ ] Sistema de Leveling funciona corretamente e é visível via comandos públicos
- [ ] Todo o sistema é resiliente (usa safe_discord, queue, locks e SQLite3)

# Demais contextos dinamicos

- A Dashboard deve ter interface moderna, limpa e responsiva
- Deve existir preview em tempo real dos embeds de boas-vindas e saída
- Todas as alterações na Dashboard devem gerar um registro auditável ("Configuração X alterada por Dono em YYYY-MM-DD")
- Sistema deve suportar alto volume de eventos simultâneos sem degradar performance
- Preparar estrutura para futuro Console/Terminal dentro da Dashboard
- Configurações devem ser salvas de forma atômica (com transactions) para evitar inconsistências
- Bot deve ter mecanismo de fallback caso alguma configuração esteja inválida
- Todos os embeds devem seguir o padrão visual premium do TARS (cores consistentes, layout limpo)
