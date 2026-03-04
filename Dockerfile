# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# Зеркало PyPI (Яндекс) — зависимость tinkoff-investments «tinkoff» не находится при недоступном PyPI на VPS.
ENV PIP_INDEX_URL=https://mirror.yandex.ru/pypi/simple
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
# git — для установки tinkoff-investments из GitHub.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch && \
    pip install --no-cache-dir "tinkoff-investments @ git+https://github.com/RussianInvestments/invest-python.git" && \
    pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
