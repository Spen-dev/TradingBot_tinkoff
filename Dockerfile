# Tinkoff trading bot — образ для VPS (код монтируется с хоста через docker-compose)
FROM python:3.11-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Слой зависимостей кэшируется, пока не меняется pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir --no-deps "tinkoff-investments @ git+https://github.com/Tinkoff/invest-python.git" && \
    pip install --no-cache-dir "cachetools>=5.2.0,<6" "grpcio>=1.39.0,<2.0.0" "protobuf>=4.21.6,<5.0.0" "python-dateutil>=2.8.2,<3.0.0" "deprecation>=2.1.0,<3.0.0" && \
    pip install --no-cache-dir "python-dotenv" "PyYAML" "pandas" "prometheus-client" "aiogram" "openai" "optuna"

COPY . .
RUN pip install --no-cache-dir --no-deps -e .

RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
