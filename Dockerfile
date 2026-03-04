# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app

# Зависимости системы (минимально для сборки пакетов)
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Копируем проект (исключения в .dockerignore)
COPY . .

# Сначала CPU-версия PyTorch (без CUDA), чтобы не забивать диск на VPS без GPU
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Установка пакета и зависимостей (stable-baselines3 подхватит уже установленный torch)
RUN pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
