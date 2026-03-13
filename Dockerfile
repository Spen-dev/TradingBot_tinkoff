# Tinkoff trading bot — образ для запуска на VPS
FROM python:3.11-slim

WORKDIR /app


# Копируем проект (исключения в .dockerignore)
COPY . .

# Torch CPU (без CUDA) — для RL в контейнере; затем tinkoff-invest из GitHub и сам проект.
# tinkoff-investments сейчас в карантине на PyPI, поэтому ставим напрямую из репозитория.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir "tinkoff-investments @ git+https://github.com/Tinkoff/invest-python.git" && \
    pip install --no-cache-dir -e .

# Директории для логов и данных
RUN mkdir -p /app/data/logs /app/learned_params && chmod -R 777 /app/data /app/learned_params

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "run_bot.py"]
