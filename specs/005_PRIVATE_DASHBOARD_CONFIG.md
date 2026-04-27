# TARS Dashboard Web

## Objective

Criar uma Dashboard Web utilizando **Flask** que permita ao dono do servidor (Carllos) configurar todo o bot TARS de forma centralizada, segura e intuitiva. A Dashboard deve consumir e salvar configurações no mesmo banco SQLite3 já utilizado pelo bot, reutilizando ao máximo os serviços e models existentes.

## Context

Atualmente todas as configurações do bot estão espalhadas ou salvas diretamente no banco. Precisamos de uma interface web amigável, segura e centralizada onde o dono possa configurar canais, cargos, mensagens de welcome, níveis de logs, auto-moderação, etc., sem precisar usar comandos no Discord.

## Domain / Package

**Domain:** Dashboard & Configuration  
**Package:** `dashboard/`

**Tecnologia escolhida:** Flask (Python) + Jinja2 + Tailwind CSS + HTMX (para experiência moderna sem React)

## Inputs

- Autenticação via Discord OAuth2 (restrita ao ID do dono)
- Requisições HTTP vindas da interface web
- Dados salvos no banco SQLite3 (`tars.sqlite3`)
- Configurações existentes dos serviços (`CoreConfigService`, `WelcomeService`, etc.)

## Expected Output

- Interface web moderna e responsiva
- Telas para configurar todos os módulos do TARS
- Preview em tempo real dos embeds de boas-vindas
- Salvamento seguro das configurações no banco SQLite3
- Aplicação das configurações em tempo real no bot (sem restart)

## Business Rules

1. **Acesso exclusivo**: Apenas o dono do servidor (definido por `TARS_OWNER_USER_ID` no `.env`) pode acessar a Dashboard.
2. **Reutilização**: A Dashboard deve usar o mesmo banco SQLite3 e os mesmos serviços do bot (`core_config_service.py`, etc.).
3. **Segurança**: Todas as rotas devem ser protegidas por autenticação.
4. **Atomicidade**: Toda alteração de configuração deve ser salva de forma atômica.
5. **Preview**: Deve existir preview dos embeds de welcome/leave antes de salvar.
6. **Sincronização**: Após salvar na Dashboard, o bot deve recarregar as configurações automaticamente (via signal ou polling).

## Main Flow

1. Dono acessa `http://seuservidor:5000`
2. Faz login via Discord OAuth2
3. Sistema verifica se o ID corresponde ao `TARS_OWNER_USER_ID`
4. Dono navega pelas seções (Welcome, Logs, Leveling, Auto-Mod, etc.)
5. Altera configurações + vê preview
6. Clica em "Salvar"
7. Dashboard chama `CoreConfigService` para persistir no banco
8. Bot detecta a mudança e aplica imediatamente

## Alternative Flows / Errors

- Usuário não autorizado tenta acessar → Redirecionar com mensagem "Acesso negado"
- Erro ao salvar configuração → Mostrar mensagem clara + rollback
- Banco SQLite3 está locked → Tentar novamente com retry
- Bot offline → Dashboard avisa que as mudanças serão aplicadas quando o bot voltar

## Classes Involved

- `CoreConfigService` (reutilizado do bot)
- `WelcomeService`
- `AuditLogService`
- `LevelingService`
- `Flask App` + Blueprints (`dashboard/blueprints/`)
- `AuthMiddleware` (verificação do dono)
- Models existentes em `bot/database/models/`

## Acceptance Criteria

- [ ] Dashboard roda em Flask e é acessível via browser
- [ ] Login restrito apenas ao dono do servidor
- [ ] Usa o mesmo banco SQLite3 do bot
- [ ] Todas as configurações salvas na Dashboard são lidas corretamente pelo bot
- [ ] Existe preview dos embeds de boas-vindas
- [ ] Interface limpa, moderna e responsiva (Tailwind + HTMX)
- [ ] Configurações de: Canais, Cargo automático, Nível de logs, Mensagens de welcome/leave, Auto-mod, XP, etc.

# Demais contextos dinamicos

- Flask foi escolhido por simplicidade, facilidade de integração com o bot e bom desempenho para esta escala
- Usar HTMX + Tailwind para ter interface moderna sem necessidade de React/Vue
- Dashboard deve rodar no mesmo servidor ou em porta separada (ex: 5000)
- Preparar estrutura para futuro Console/Terminal dentro da Dashboard
- Deve ter modo "Dark" por padrão (estilo cyber/premium)
- Todas as rotas sensíveis devem ter proteção CSRF
- Logs da Dashboard devem ser salvos separadamente para auditoria
- Planejar Docker Compose no futuro para rodar bot + dashboard juntos
