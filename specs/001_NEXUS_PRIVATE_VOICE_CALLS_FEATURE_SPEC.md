# PRIVATE_VOICE_CALLS_FEATURE_SPEC.md

Chamadas Privadas Temporárias

## Canal Fixo (Entrada)

Nome exato do canal: • Criar Call Privada
ID do Canal: 1498213727932256308
Tipo: Voice Channel (permanente)

## Objetivo

Quando um usuário entrar no canal de voz "• Criar Call Privada", o bot deve:

1. Criar automaticamente uma chamada de voz temporária privada para ele.
2. Mover o usuário para essa nova call em poucos segundos.
3. Enviar um embed interativo de configuração dentro do chat da nova call.
4. Permitir que o dono configure a call (limite, convites, permissões, etc.).
5. Deletar a call automaticamente quando todos saírem dela.

## Configuração via .env

PRIVATE_VOICE_HUB_ID=1498213727932256308

## Constantes

PRIVATE_CALL_TOPIC_PREFIX = "private_voice_call:owner_id="
PRIVATE_CALL_NAME_TEMPLATE = "Call Privada - {display_name}"

## Regras de Negócio (Obrigatórias)

1. O sistema ativa apenas quando alguém entra no canal "• Criar Call Privada" (ID: 1498213727932256308).
2. Cada usuário pode ter no máximo 1 call privada ativa por vez.
3. A call temporária deve ter nome no formato: "Call Privada - NomeDoUsuário"
4. Quando a call ficar vazia → deletar o canal automaticamente.
5. Apenas o dono da call pode usar os botões de configuração.
6. Convites são enviados por DM com botão direto para entrar na call.
7. Bot precisa das permissões: Manage Channels, Move Members, Connect, Speak.

## Embed de Controle (no chat da call criada)

Título: ⚙️ Configuração da Call Privada
Cor: 0x5865F2 (azul Discord) ou roxo

Botões principais:
• 👥 Definir Limite de Usuários
• 📨 Convidar Usuário
• 🔒 Alterar Visibilidade
• 🎤 Soundboard (Ativar/Desativar)
• 📺 Screen Share (Ativar/Desativar)
• 🔄 Renomear Call
• 🗑️ Deletar Call Agora

## Fluxo Principal

1. Usuário entra no canal "• Criar Call Privada"
2. Bot detecta a entrada (on_voice_state_update)
3. Cria canal de voz temporário "Call Privada - {Nome}"
4. Move o usuário automaticamente para o novo canal
5. Envia embed de controle no chat da call
6. Mensagem de boas-vindas simples

## Fluxo de Auto-Delete

Quando o último usuário sair da call privada → o bot deleta o canal.

## Estrutura Recomendada de Arquivos

bot/cogs/voice/private_voice_calls.py
bot/utils/private_voice_manager.py
bot/utils/private_voice_view.py
bot/utils/private_voice_embeds.py

## Acceptance Criteria

- [ ] Ao entrar no canal "• Criar Call Privada" o usuário é movido automaticamente
- [ ] Call temporária é criada com nome correto
- [ ] Embed de controle aparece no chat da call
- [ ] Apenas o dono consegue configurar a call
- [ ] Convites funcionam via DM com botão
- [ ] Call é deletada quando esvazia
- [ ] Segue rigorosamente o AGENTS.txt

## Commit Sugerido

feat: implementar sistema de chamadas privadas temporárias

## Observações

- Manter simples e funcional
- Visual clean e profissional (sem exagerar no futurismo)
- Fácil de manter e expandir
