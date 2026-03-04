# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# Torch CPU (без CUDA) — для RL в контейнере; затем tinkoff-invest и проект с sb3/gymnasium.
# Проверку tinkoff не делаем при сборке (editable install может её ломать); CMD при старте ставит tinkoff-invest.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir tinkoff-invest && \
    pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Установка tinkoff-invest при старте — страховка от кэша/старого образа (если в образе пакета нет)
CMD ["sh", "-c", "pip install --no-cache-dir -q tinkoff-invest && exec python run_bot.py"]
