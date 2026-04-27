# 001_private_command_room_panel_patchs_spec

## Objetivo

Cancelar a feature `/g private` e remover a criação de canais privados por
usuário.

## Correção de Produto

A abordagem de criar uma categoria e um canal por usuário não deve ser usada.
O bot não deve expor `/g private` nem qualquer cog relacionado a salas privadas.

Comandos futuros do bot que forem executados no canal global permitido devem
responder de forma ephemeral quando a resposta precisar ser visível apenas ao
usuário que executou o comando.

## Regras Que Sobrescrevem A Spec Base

1. O comando `/g private` deixa de existir.
2. O grupo `/g` deixa de existir enquanto não houver outro comando de geração.
3. Nenhuma categoria, canal de texto, topic ou overwrite é criado para usuário.
4. Toda lógica baseada em topic `private_command_channel:user_id=<USER_ID>` deixa
   de fazer parte desta feature.
5. Permissões de canal privado deixam de fazer parte desta feature.
6. O bot deve iniciar sem cogs customizadas relacionadas a esta feature.
7. A árvore de application commands deve ser sincronizada sem `/g private`.

## Acceptance Criteria

- [ ] `/g private` não aparece na lista de comandos.
- [ ] O bot não cria categorias ou canais por usuário.
- [ ] `discover_cogs()` retorna lista vazia enquanto não houver novos cogs.
- [ ] Código segue AGENTS.md.
