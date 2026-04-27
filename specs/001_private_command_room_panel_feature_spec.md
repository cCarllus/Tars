# 001_private_command_room_panel_feature_spec

## Objetivo

Implementar o comando /g private para abrir um painel privado interativo que permite ao usuário criar sua "Sala de Comandos Privada".

## Contexto do Sistema de Comandos

- Todos os comandos do tipo "/g" são comandos de GERAÇÃO (gerar algo).
- Comandos sem prefixo "/g" são comandos de execução direta/universal.
- Exemplos:
  - /g private → Gera painel de criação de sala privada
  - /ban → Executa banimento diretamente
  - /clear → Executa limpeza diretamente

## Objetivo da Feature

Permitir que cada usuário tenha seu próprio espaço privado para usar comandos do bot sem poluir os canais públicos.

Ao usar /g private no canal global permitido, o bot mostra um painel com botões. O primeiro botão funcional é:

💬 Sala de comandos

Ao clicar, o bot cria (ou recupera) uma categoria privada + canal de texto privado para o usuário.

## Canal Global Permitido

ID: 1498085284410298590
Todos os comandos /g devem ser executados apenas neste canal.

## Estrutura Recomendada

bot/cogs/admin/private_channels.py ← Arquivo principal
bot/utils/checks.py
bot/utils/embed.py
bot/config.py
bot/utils/private_channel_manager.py ← (recomendado)

## Configuração via .env

GLOBAL_COMMAND_CHANNEL_ID=1498085284410298590

## Constantes

PRIVATE_CHANNEL_TOPIC_PREFIX = "private_command_channel:user_id="
PRIVATE_CATEGORY_NAME_FORMAT = "══| {name} |══"
PRIVATE_TEXT_CHANNEL_NAME = "📋・sala-de-comandos"

## Regras de Negócio (Obrigatórias)

1. O comando /g private só funciona no canal global (1498085284410298590).
2. Se usado em outro canal → responder: "Use os comandos do bot no canal correto: <#1498085284410298590>"
3. O comando /g private abre um embed ephemeral com painel de botões.
4. Botões iniciais:
   - 💬 Sala de comandos (ativo)
5. Apenas o dono do painel pode interagir com os botões.
6. Cada usuário pode ter no máximo 1 sala de comandos.
7. A verificação de sala existente deve ser feita pelo topic do canal:
   private_command_channel:user_id=<USER_ID>
8. Nome da categoria: normalizado + "══| NOME |══"
9. Nome do canal: sempre "📋・sala-de-comandos"
10. Permissões:
    - @everyone → view_channel = False
    - Dono da sala → view_channel, send_messages, read_message_history = True
    - Bot → manage_channels + todas as permissões necessárias
11. Cooldown de 30 segundos por usuário no comando /g private.
12. Nunca criar canais duplicados.
13. Se o canal for deletado manualmente, criar um novo na próxima solicitação.

## Fluxo Principal

1. Usuário executa /g private no canal global
2. Bot valida canal e responde com embed + View (ephemeral)
3. Usuário clica em "💬 Sala de comandos"
4. Bot verifica se já existe canal pelo topic
5. Se não existir → cria categoria + canal
6. Se existir → retorna o canal existente
7. Bot responde: "Sua sala de comandos está pronta: #📋・sala-de-comandos"

## Tratamento de Erros

- Comando fora do canal global → mensagem clara
- Outro usuário clica no painel → "Este painel pertence a outro usuário."
- Bot sem permissão Manage Channels → mensagem + log de erro
- Erro inesperado → "Não consegui executar este comando." + logger.error(exc_info=True)
- Nome do usuário inválido após sanitização → fallback "Usuário"

## Normalização de Nome

- Converter para maiúsculo
- Remover emojis e caracteres especiais problemáticos
- Substituir espaços e caracteres inválidos por "-"
- Limitar em 80 caracteres
- Fallback: "Usuário"

## Classes e Responsabilidades

PrivateChannelsCog - Comando /g private - Gerenciamento do painel

PrivatePanelView - Botões - interaction_check (verificar dono) - create_command_room()

PrivateChannelManager (recomendado em utils) - find_existing_private_channel() - get_or_create_private_command_channel() - create_private_category() - create_private_text_channel() - sanitize_category_name()

## Acceptance Criteria

- [ ] Comando /g private existe e funciona
- [ ] Só funciona no canal global correto
- [ ] Abre painel com botões (1 ativo, 2 disabled)
- [ ] Botão Sala de comandos cria ou recupera sala corretamente
- [ ] Usa topic para identificação
- [ ] Permissões privadas corretas
- [ ] Não cria duplicados
- [ ] Segue AGENTS.txt (type hints, docstrings, ruff, black, mypy, etc.)
- [ ] Usa logger (nunca print)
- [ ] Código em bot/cogs/admin/private_channels.py

## Commit Sugerido

feat: adicionar painel privado /g private com criação de sala de comandos

## Observações Finais

- Esta feature serve como base para futuros botões no painel (/g suporte, /g ticket, etc.)
- Manter o código limpo e extensível
- Preparar estrutura para futura integração com banco de dados
