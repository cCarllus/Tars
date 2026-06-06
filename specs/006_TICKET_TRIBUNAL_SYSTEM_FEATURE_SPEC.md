# 006_TICKET_TRIBUNAL_SYSTEM_FEATURE_SPEC.md

## Objective

Implementar um sistema completo de **Tickets** (Suporte + Denúncias/Report) e **Tribunal** para o TARS, permitindo que qualquer usuário abra tickets de forma organizada, com triagem por administradores, canais privados temporários e escalonamento para Tribunal com votação judicial.

O objetivo principal é substituir reports caóticos e bans diretos por um processo estruturado, auditável e justo, alinhado ao estilo "caos controlado" do servidor.

## Context

O servidor possui alto volume de interações zoeira/humor negro. É necessário:

- Permitir que qualquer membro reporte problemas ou peça suporte.
- Evitar abusos e bans arbitrários.
- Centralizar a triagem em um canal visível apenas para staff.
- Ter canais privados por caso (texto + voz opcional).
- Possibilitar escalonamento para Tribunal com juízes e votação formal.
- Todas as configurações (canais, cargos permitidos, etc.) devem ser feitas **exclusivamente via Dashboard**.

## Domain / Package

**Domain:** Moderation & Support System  
**Package:** `bot/cogs/tickets/`

**Arquivos principais a criar:**

- `bot/cogs/tickets/ticket_cog.py`
- `bot/cogs/tickets/tribunal_cog.py` (ou integrado no mesmo cog)
- `bot/views/ticket_views.py`
- `bot/modals/ticket_modals.py`
- `bot/database/models/ticket_models.py`
- `bot/services/ticket_service.py`
- Atualizações na Dashboard (`dashboard/routes/tickets.py` e templates)

## Inputs

- Comandos Slash:
  - `/reportar [@alvo] <motivo>` (qualquer usuário)
  - `/suporte <descrição>`
  - `/tribunal abrir` (apenas staff, para casos manuais)
- Interações de botões e selects (Aceitar, Fechar, Escalar, Votar, etc.)
- Configurações da Dashboard (canal de triagem, cargos de staff/juiz, tempos de expiração, etc.)

## Expected Output

- Mensagem organizada no canal de triagem `#・suporte-denuncias` (visível só para staff).
- Canais privados temporários por ticket (`📋 Ticket #XXXX - @usuario`).
- Sistema de votação no Tribunal.
- Logs completos no `#・tars-logs`.
- Fechamento automático ou manual com arquivamento.

## Business Rules

1. **Configuração Centralizada**: Todos os canais (triagem, logs) e cargos (Staff, Juiz, etc.) devem ser configurados **exclusivamente na Dashboard**.
2. **Acesso**:
   - Qualquer membro pode abrir report/suporte.
   - Apenas cargos configurados como "Staff" podem aceitar/fechar tickets.
   - Apenas cargos "Juiz" ou "Admin" podem votar em Tribunal.
3. **Tipos de Ticket**:
   - `support` → Suporte geral.
   - `report` → Denúncia (pode ser escalado para Tribunal).
4. **Canais Privados**:
   - Visíveis apenas para: criador do ticket + envolvidos + staff/juízes.
   - Opcional: canal de voz.
5. **Tribunal**:
   - Votação por maioria (configurável).
   - Opções: Absolver, Timeout, Kick, Ban (temporário/permanente), Outros.
6. **Persistência**: Todos os tickets salvos no SQLite com histórico completo.
7. **Segurança**: Rate limiting anti-spam, logs auditáveis, permissões granulares.
8. **Limpeza**: Tickets fechados são arquivados ou deletados após X horas (configurável na Dashboard).

## Main Flow

1. Usuário executa `/reportar` ou `/suporte`.
2. Bot cria mensagem no canal de triagem com embed + botões (Aceitar / Fechar).
3. Staff clica **Aceitar** → Bot cria categoria e canais privados + envia embed inicial.
4. No canal privado:
   - Opções: Adicionar provas, Escalar para Tribunal, Encerrar Ticket.
5. Se escalado para Tribunal → Ativa sistema de votação entre juízes.
6. Ao encerrar: Executa punição (se aplicável), envia log completo, deleta/arquiva canais.

## Alternative Flows / Errors

- Canal de triagem não configurado → Alerta DM para dono + fallback.
- Usuário sem permissão → Mensagem amigável de erro.
- Ticket expirado → Auto-fechamento com notificação.
- Erro ao criar canal → Log detalhado + retry.
- Staff tenta votar sem cargo de Juiz → Negado.

## Classes Involved

- `TicketService` — Gerencia criação, estado e fechamento.
- `TribunalService` — Lógica de votação e punições.
- `TicketView`, `TribunalView` — Botões e selects.
- `TicketModal` — Formulários para motivo/provas.
- `TicketModel`, `TicketParticipant`, `VoteModel` — Models do banco.
- Integração com `AuditLogService` e configurações da Dashboard.

## Acceptance Criteria

- Comandos `/reportar` e `/suporte` funcionam para qualquer usuário.
- Canal de triagem mostra apenas para cargos configurados.
- Canais privados são criados corretamente com permissões exatas.
- Sistema de Tribunal permite votação e aplicação automática de punições.
- Toda ação gera log auditável.
- Todas as configs vêm da Dashboard.
- Código segue PEP8, Black, Ruff, type hints e padrões do projeto.
- Testes unitários básicos para fluxos principais.

# Demais contextos dinâmicos

- Interface da Dashboard deve permitir visualizar todos tickets abertos/fechados com filtro e busca.
- Suporte a anonimato opcional em reports (quem reportou visível só para staff).
- Integração futura com Auto-Mod (auto-criar ticket em casos graves).
- Manter experiência premium e visual consistente com o TARS (embeds bonitos, cores temáticas).
- Preparar para futuro sistema de "Prioridade" em tickets (grave, média, baixa).

## Incremento 2026-06-06 — UX, Segurança, Auditoria e Dashboard

**Status:** Done

### Funcionalidades adicionadas

- Embeds padronizados por `create_ticket_embed()` com tema por tipo:
  - `report`: vermelho
  - `support`: azul
  - `tribunal`: dourado
- Footer, timestamp, thumbnail e campos base padronizados para embeds de tickets.
- Modal dedicado de provas com descrição e links um por linha.
- Registro automático de mensagens com anexos no canal privado como provas do ticket.
- Persistência dedicada de provas em `ticket_proofs`.
- Transcript automático em `.txt` ao fechar tickets com histórico do canal e provas registradas.
- Envio do transcript para canal configurado de transcripts, com fallback para logs/sistema.
- Notificações por DM ao criador quando o ticket é aceito e quando é fechado.
- Rate limit configurável pela Dashboard:
  - quantidade máxima por usuário
  - janela de tempo em minutos
- Anti-spam por similaridade simples de motivo dentro da janela configurada.
- Persistência dedicada de ações importantes em `ticket_action_logs`.
- Dashboard `/dashboard/tickets` com:
  - filtros por busca, tipo, status e data
  - status com cores
  - coluna de link do canal
  - ação rápida para fechar diretamente
- Configurações novas na Dashboard:
  - canal de transcripts
  - notificações DM
  - limite de tickets por usuário
  - janela do limite

### Testes adicionados/atualizados

- Persistência de provas.
- Persistência de action logs.
- Consulta de rate limit e anti-spam.
- Geração básica de transcript.
- Fechamento direto pela Dashboard.
