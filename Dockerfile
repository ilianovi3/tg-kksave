# --- ЭТАП 1: Сборка зависимостей ---
FROM python:3.12-slim AS builder

# Копируем бинарники uv из официального образа
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# UV_COMPILE_BYTECODE — компилируем .pyc для быстрого старта
# UV_LINK_MODE=copy — копируем из кэша вместо хардлинков (важно для multi-stage)
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Ставим только зависимости — слой кэшируется, пока не менялись lock-файлы
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# --- ЭТАП 2: Финальный образ ---
FROM python:3.12-slim
WORKDIR /app

# Копируем готовое виртуальное окружение из builder
COPY --from=builder /app/.venv /app/.venv

# Кладём venv в PATH, чтобы python и пакеты были доступны напрямую
ENV PATH="/app/.venv/bin:$PATH"

COPY . ./

CMD ["python", "main.py"]
