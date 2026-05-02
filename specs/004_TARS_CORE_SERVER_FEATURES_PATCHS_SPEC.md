# TARS Core Server Patchs

## Patch 001 - Links permitidos na auto-moderação

### Contexto

O servidor deve permitir mensagens com links no Discord. A auto-moderação não
deve remover mensagens apenas por conterem URLs, mesmo que existam configurações
antigas de bloqueio de links salvas no banco.

### Regras

- Links HTTP/HTTPS enviados por membros devem ser permitidos.
- A auto-moderação pode continuar removendo mensagens por palavras bloqueadas.
- Configurações antigas de `block_links` e `allowed_links` devem ser ignoradas.
- A Dashboard não deve oferecer controle para bloquear links enquanto essa regra
  estiver ativa.

### Critérios de Aceite

- [ ] Uma mensagem contendo link não permitido por whitelist antiga não é
  deletada.
- [ ] Uma mensagem contendo palavra bloqueada continua sendo deletada.
- [ ] Salvar a Dashboard não reativa bloqueio de links.
