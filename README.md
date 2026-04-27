# Tars Discord Bot

Bot Discord em Python com comandos organizados por cogs.

## Comando para visualizar e implementar uma spec

1. Read AGENTS.md and specs/XXX_XXX_feature_spec.md
2. Then implement the feature exactly as specified.
3. Run the relevant tests after the implementation.

## Comecar

```bash
python3.11 -m venv myenv
source myenv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Preencha o `.env` e rode:

```bash
python -m bot.main
```

No macOS, os comandos de voz precisam de:

```bash
brew install ffmpeg opus
```

## Comandos

O bot foi resetado para comecar do zero e ainda nao possui comandos customizados.
Novos comandos devem ser adicionados como cogs em `bot/cogs/`.
O comando universal padrao para acionar comandos de texto e `/`.

## Desenvolvimento

Leia [AGENTS.md](AGENTS.md) antes de alterar o projeto.

Cheque qualidade com:

```bash
ruff check . --fix
black .
mypy .
pytest
python -m compileall main.py bot tests
```
