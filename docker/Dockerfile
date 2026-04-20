FROM python:3.10-slim

LABEL maintainer="Your Name"
LABEL version="1.0.0"
LABEL description="AI Trading Bot"

# Создаем пользователя (безопасность)
RUN useradd -m -u 1000 trader && \
    mkdir -p /app /data /logs /models && \
    chown -R trader:trader /app /data /logs /models

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY src/ ./src/

# Права на папки
VOLUME ["/data", "/logs", "/models"]

USER trader

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import src.bot; print('OK')" || exit 1

CMD ["python", "-m", "src.bot"]