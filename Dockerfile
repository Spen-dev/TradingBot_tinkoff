# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# Torch CPU (без CUDA) — для RL в контейнере; затем tinkoff-invest из GitHub (без его зависимостей) и сам проект.
# tinkoff-investments в карантине на PyPI и тянет недоступный пакет tinkoff, поэтому ставим его из GitHub с --no-deps,
# а необходимые зависимости (cachetools, grpcio, protobuf, python-dateutil, deprecation) докручиваем вручную.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir --no-deps "tinkoff-investments @ git+https://github.com/Tinkoff/invest-python.git" && \
    pip install --no-cache-dir "cachetools>=5.2.0,<6" "grpcio>=1.39.0,<2.0.0" "protobuf>=4.21.6,<5.0.0" "python-dateutil>=2.8.2,<3.0.0" "deprecation>=2.1.0,<3.0.0" && \
    pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
