# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# Сначала CPU-версия PyTorch (без CUDA), чтобы не забивать диск на VPS без GPU
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Явно ставим клиент Тинькофф (пакет tinkoff-invest, импорт: tinkoff.invest)
RUN pip install --no-cache-dir tinkoff-invest

# Установка пакета и остальных зависимостей (stable-baselines3 подхватит уже установленный torch)
RUN pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
