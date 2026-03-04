# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# Один слой установки: torch (CPU), tinkoff-invest и проект — чтобы tinkoff гарантированно был в окружении
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir tinkoff-invest && \
    pip install --no-cache-dir -e . && \
    python -c "from tinkoff.invest.exceptions import RequestError; print('tinkoff OK')"

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Установка tinkoff-invest при старте — страховка от кэша/старого образа (если в образе пакета нет)
CMD ["sh", "-c", "pip install --no-cache-dir -q tinkoff-invest && exec python run_bot.py"]
