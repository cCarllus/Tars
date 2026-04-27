# ARCHITECTURE_GUIDELINES.md

Propósito: Definir padrões técnicos, boas práticas e estratégias de arquitetura para que o bot TARS seja estável, seguro e capaz de escalar para servidores com 20.000+ usuários ativos sem colapsar.

1. Princípios Fundamentais

---

- Tudo deve ser assíncrono (async/await)
- Nunca bloquear o event loop principal do discord.py
- Separar claramente listeners, lógica de negócio e operações pesadas
- Priorizar: Estabilidade > Performance > Novas Features
- Pensar sempre em "o que acontece se 500 pessoas entrarem no hub de call ao mesmo tempo?"
- Todo código novo deve ser pensado para escala desde o início

2. Estrutura de Pastas Recomendada (Atualizada)

---

bot/
├── cogs/
│ ├── voice/
│ │ └── private_voice_calls.py
│ └── ... (futuras features)
├── core/
│ ├── **init**.py
│ ├── bot.py
│ ├── config.py
│ └── logger.py
├── utils/
│ ├── rate_limiter.py
│ ├── safe_discord.py
│ ├── locks.py
│ ├── queue_manager.py
│ ├── database.py
│ ├── cleanup.py
│ └── helpers.py
├── models/
│ └── voice.py
├── services/
│ └── voice_service.py
├── tasks/
│ └── background_tasks.py
└── data/ (ou database/)
└── migrations/

3. Rate Limiting & Proteção contra Sobrecarga

---

- Rate Limiter próprio (por usuário + por guild + global)
- Cooldowns específicos por ação (criar call = mais restrito)
- Bucket por tipo de ação (voice_creation, message_sending, etc.)
- Implementar backpressure quando a fila estiver cheia
- Monitorar e rejeitar requests quando o bot estiver sob alta carga

4. Concorrência e Thread Safety

---

- Usar asyncio.Lock() por usuário em ações críticas (criação de call)
- Usar asyncio.Lock() por guild em operações globais
- Evitar condição de corrida usando "check-then-act" com locks
- Nunca assumir que duas operações não vão acontecer ao mesmo tempo

5. Persistência de Estado (Obrigatória)

---

- Usar SQLite inicialmente (fácil e rápido)
- Planejar migração futura para PostgreSQL + Redis
- Tabelas mínimas iniciais:
  - active_voice_sessions (id, guild_id, owner_id, channel_id, created_at, last_updated)
  - command_execution_log
  - action_audit_log
  - rate_limit_hits
- Sempre fazer cleanup automático no startup (remover sessões órfãs)
- Usar transactions para evitar dados inconsistentes

6. Comunicação Segura com a Discord API (safe_discord.py)

---

Todas as chamadas à API devem passar por funções seguras:

- safe_send_message()
- safe_create_voice_channel()
- safe_move_member()
- safe_edit_channel_permissions()
- safe_delete_channel()
- safe_send_dm()

Cada função deve conter:

- Retry automático (3~5 tentativas)
- Exponential backoff + jitter
- Tratamento específico de discord.RateLimitError (429)
- Timeout por operação
- Logging completo de latência e status

7. Logging Estruturado

---

- Usar structlog ou logging com JSON
- Todo log importante deve conter: user_id, guild_id, action, success, duration_ms, error
- Níveis: INFO para ações normais, WARNING para rate limits, ERROR para falhas críticas
- Logar todas as criações/exclusões de calls

8. Background Tasks e Filas

---

- Usar asyncio.Queue para operações pesadas
- Criar um worker dedicado para processar a fila de Discord API
- Background tasks para:
  - Cleanup periódico de calls órfãs
  - Reconciliação de estado
  - Monitoramento de rate limits

9. Estratégias de Escalabilidade

---

- Single process → Multi-process / Sharding (quando necessário)
- Cache em memória (aiocache ou Redis) para sessões ativas
- Monitoramento de métricas (latência, uso de CPU, quantidade de calls ativas)
- Graceful shutdown (deletar ou salvar estado antes de desligar)

10. Boas Práticas para Features de Alta Interação

---

- Toda feature que cria canais ou move usuários deve:
  - Usar lock por usuário
  - Persistir estado imediatamente
  - Usar fila se houver mais de 1 operação Discord
  - Ter mecanismo de retry + fallback
- Sempre implementar cleanup automático
- Testar com cenários de pico (simular 50-100 entradas simultâneas)

11. Ordem de Implementação (Prioridade Atual)

---

1. safe_discord.py + rate_limiter.py + locks.py
2. database.py + models de voice sessions
3. Melhorar o sistema de Private Voice Calls com as novas camadas
4. queue_manager.py + background workers
5. Cleanup automático no startup
6. Logging estruturado completo

## Última Regra (Mais Importante)

"Não adianta ter features bonitas se o bot cai ou perde dados quando 500 pessoas usam ao mesmo tempo.
Estabilidade em escala é mais importante que qualquer nova funcionalidade."
