# Tars Discord Bot

Bot Discord em Python com comandos organizados por cogs.

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

```text
$play nome ou url da musica
$pause
$resume
$skip
$queue
$agenda
$adicionar texto da tarefa
$remover numero_da_tarefa
$limpar quantidade
$start
$finish
```

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

