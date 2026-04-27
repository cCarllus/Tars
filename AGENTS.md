# AGENTS.md

## Spec-Driven Development

All feature implementation in this project follows a Spec-Driven Development approach.

## Feature Specs

Before implementing any feature:

1. Read the relevant spec in `specs/`.
2. Each feature may have multiple spec files:
   - `<id>_<feature>_feature_spec.md` (base behavior)
   - `<id>_<feature>_patchs_spec.md` (bug fixes, optional)
   - `<id>_<feature>_increments_spec.md` (improvements, optional)
3. Always read the base spec first, then check for patchs and increments.
4. Treat all specs together as the source of truth for behavior and acceptance criteria.
5. Patchs override incorrect behavior from the base spec.
6. Increments extend the feature without breaking existing behavior.
7. Do not invent requirements not present in the specs.
8. Do not rewrite the entire feature when applying small changes.
9. Follow repository architecture and coding standards after reading the spec.

---

## 1. Principios Fundamentais

- Codigo limpo, legivel e profissional e mais importante que "so funcionar".
- Manter consistencia acima de tudo.
- Seguir PEP 8, Black e Ruff.
- Nunca usar `print()` em producao. Use sempre `bot.logger.logger`.
- Pensar em escalabilidade e manutencao. O bot deve suportar muitas cogs.
- Nunca adicionar dependencias desnecessarias.
- Seguranca primeiro: nunca expor tokens, chaves de API ou dados sensiveis.

## 2. Estrutura Obrigatoria Do Projeto

```text
.
├── bot/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── logger.py
│   ├── database/
│   ├── cogs/
│   │   └── __init__.py
│   ├── views/
│   ├── modals/
│   ├── tasks/
│   └── utils/
├── tests/
├── .env.example
├── pyproject.toml
├── ruff.toml
├── requirements.txt
├── README.md
├── AGENTS.md
└── .gitignore
```

Regra de ouro: todo novo comando ou evento deve ficar dentro de um Cog em
`bot/cogs/`.

## 3. Como Comecar

1. Crie ou ative um ambiente virtual:

```bash
python3.11 -m venv myenv
source myenv/bin/activate
```

2. Instale as dependencias:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Instale dependencias de audio no macOS:

```bash
brew install ffmpeg opus
```

4. Copie `.env.example` para `.env` e preencha os valores.

5. Rode o bot:

```bash
python -m bot.main
```

`python main.py` existe apenas como entrada de compatibilidade.

## 4. Configuracao

- Usar `pydantic-settings` v2.
- `.env` nunca vai para o git.
- Todas as configuracoes devem vir de `bot.config.settings`.
- Sempre adicionar novas variaveis tambem em `.env.example`.

Variaveis atuais:

```env
DISCORD_TOKEN=
COMMAND_PREFIX=/
LOG_LEVEL=INFO
```

## 5. Padroes De Codigo

- Python 3.11+.
- Usar `async`/`await` sempre que a API for I/O ou Discord.
- Type hints em todo codigo novo.
- Docstrings no estilo Google para classes, funcoes publicas e blocos nao obvios.
- Nomes internos em ingles.
- Textos de comandos e mensagens para usuario em PT-BR.
- Arquivos: `snake_case.py`.
- Classes: `PascalCase`.
- Funcoes e variaveis: `snake_case`.
- Constantes: `UPPER_CASE`.

## 6. Regras De Qualidade

Todo codigo deve passar, quando as ferramentas estiverem instaladas:

```bash
ruff check . --fix
black .
mypy .
pytest
```

Antes de finalizar qualquer mudanca, rode pelo menos:

```bash
python -m compileall main.py bot tests
```

Proibido:

- `except: pass`
- `print()` em codigo de producao
- `from module import *`
- codigo comentado desnecessario
- strings magicas quando uma constante clara resolver
- segredo hardcoded em qualquer arquivo

## 7. Logging

Use sempre:

```python
from bot.logger import logger

logger.info("Mensagem")
logger.error("Erro", exc_info=True)
```

Para excecoes, prefira:

```python
logger.exception("Contexto do erro")
```

## 8. Fluxo De Trabalho Dos Agentes

1. Ler este `AGENTS.md` antes de qualquer alteracao.
2. Verificar o estado do repositorio:

```bash
git status --short
```

3. Fazer mudancas mantendo os padroes.
4. Rodar Ruff, Black, MyPy e testes quando possivel.
5. Commits, quando solicitados, devem ser claros e em portugues:

```text
feat: adicionar comando banir usuario
fix: corrigir permissao no mute
refactor: reorganizar embeds
```

## 9. Boas Praticas Adicionais

- Criar helpers compartilhados em `bot/utils/`.
- Usar `bot/utils/embed.py` para padronizar embeds.
- Centralizar tratamento de erros quando o comportamento se repetir.
- Respeitar rate limits da Discord.
- Usar hybrid commands quando fizer sentido para a UX.
- Nunca bloquear a event loop com chamadas de rede ou CPU pesadas.
- Para chamadas bloqueantes, use `asyncio.to_thread()` ou uma API async.
- Manter players, caches e estados separados por guild ou usuario.

## 10. Comandos Existentes

O bot foi resetado para comecar do zero e nao possui comandos customizados.
Como o comando universal padrao e `/`, todo novo comando deve seguir esse
prefixo quando for comando de texto.

Ao criar comandos, adicione uma cog em `bot/cogs/` e mantenha mensagens de
usuario em PT-BR.

## 11. Responsabilidades Dos Agentes

- Manter o codigo limpo mesmo em correcoes rapidas.
- Nunca remover docstrings uteis sem motivo.
- Atualizar este `AGENTS.md` quando surgir nova regra importante.
- Documentar comportamentos nao obvios.
- Sempre perguntar: "Se eu fosse manter esse bot daqui 2 anos, ficaria feliz
  com esse codigo?"

## Ultima Regra

Se tiver duvida sobre como fazer algo, faca da forma mais limpa, clara e
padronizada possivel. Prefira sempre consistencia e clareza.
