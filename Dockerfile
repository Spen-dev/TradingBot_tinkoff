# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# PyPI — для poetry-core при сборке из git; зеркало и PyTorch — доп. индексы.
ENV PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_EXTRA_INDEX_URL="https://mirror.yandex.ru/pypi/simple https://download.pytorch.org/whl/cpu"
# tinkoff-investments из git с --no-deps: пакет «tinkoff» (зависимость в pyproject) нет на публичном PyPI.
# Рантайм-зависимости ставим вручную (cachetools, grpcio, protobuf, python-dateutil, deprecation).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir poetry-core && \
    pip install --no-cache-dir torch && \
    pip install --no-cache-dir "cachetools>=5.2.0,<6" "grpcio>=1.59.3" "protobuf>=4.25.1,<5" "python-dateutil>=2.8.2" "deprecation>=2.1.0,<3" && \
    pip install --no-cache-dir --no-build-isolation --no-deps "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git" && \
    pip install --no-cache-dir -e . --no-deps && \
    pip install --no-cache-dir python-dotenv PyYAML pandas prometheus-client aiogram gymnasium stable-baselines3

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
