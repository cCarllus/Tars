# TARS Core Server Increments

## Increment 001 - Domínios proibidos na auto-moderação

### Contexto

A auto-moderação deve continuar permitindo links HTTP/HTTPS comuns, mas deve
remover convites de outros servidores do Discord quando o domínio estiver
listado em um arquivo JSON versionado.

### Regras

- O bloqueio geral de links continua desativado.
- Configurações antigas de `block_links` e `allowed_links` continuam ignoradas.
- A auto-moderação deve bloquear apenas URLs cujo domínio esteja em
  `bot/database/blocked_domains.json`.
- O arquivo JSON deve usar a chave `blocked_domains`.
- O domínio inicial bloqueado deve ser `https://discord.gg/`.
- Novos domínios devem poder ser adicionados ao JSON sem alterar o código.

### Critérios de Aceite

- [ ] Uma mensagem contendo `https://discord.gg/SUkSusyu` é deletada.
- [ ] Uma mensagem contendo link HTTP/HTTPS comum continua permitida.
- [ ] Uma mensagem contendo palavra bloqueada continua sendo deletada.
- [ ] O bloqueio antigo por whitelist não é reativado.
