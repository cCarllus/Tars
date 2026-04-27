FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/myenv \
    PATH="/app/myenv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv "$VIRTUAL_ENV" \
    && python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "bot.main"]
