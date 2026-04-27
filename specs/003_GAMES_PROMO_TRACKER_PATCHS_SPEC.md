# Games Promo Tracker Patch Spec

## Patch: Cadência diária do modo automático

O modo automático não deve publicar várias vezes no mesmo dia.

Nova regra:

- Quando o bot publicar uma mensagem automática de promoções em um dia, ele não
  deve publicar outra mensagem automática nesse mesmo dia.
- Depois de publicar, o bot deve ficar 2 dias completos sem publicar novas
  mensagens automáticas.
- A próxima publicação automática só pode ocorrer no terceiro dia após a última
  publicação automática.
- O comando manual `/games promo` não é afetado por essa janela.

Exemplo:

- Dia 1: publica 1 vez.
- Dia 2: não publica.
- Dia 3: não publica.
- Dia 4: pode publicar novamente 1 vez.
