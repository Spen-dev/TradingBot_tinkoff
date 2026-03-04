# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# PyPI — для poetry-core при сборке из git; зеркало и PyTorch — доп. индексы.
ENV PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_EXTRA_INDEX_URL="https://mirror.yandex.ru/pypi/simple https://download.pytorch.org/whl/cpu"
# Сначала ставим poetry-core, чтобы subprocess при pip install из git его нашёл (на зеркале его нет).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir poetry-core && \
    pip install --no-cache-dir torch && \
    pip install --no-cache-dir --no-build-isolation "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git" && \
    pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
