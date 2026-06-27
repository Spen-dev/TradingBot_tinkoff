# Tinkoff Trading Bot

Автоматический ребаланс портфеля MOEX (Tinkoff Invest API): стратегии adaptive / RL / ai, динамический состав (Finam, MOEX ISS, macro-новости, OpenRouter LLM), Telegram-управление, Docker на VPS.

## Возможности

- **Брокер:** Tinkoff Invest (sandbox / real), retry при сбоях API
- **Стратегии:** adaptive, momentum, mean reversion, RL, **ai** (OpenRouter: Gemini Flash Lite + fallback)
- **Динамический состав:** Finam, MOEX, macro-события (RSS → LLM), pick_best_advisor
- **Автоматизация (`ops`):** автостарт sandbox, healthcheck, бэкап learned_params, алерт баланса OpenRouter, macro-триггеры, watchdog → restart
- **Деплой:** Docker Compose, GitHub Actions → VPS ([DEPLOY.md](DEPLOY.md))

## Требования

- Python 3.10+
- Токены: Tinkoff Invest API, Telegram Bot
- Опционально: `OPENROUTER_API_KEY`, `FINAM_API_TOKEN`

## Установка

```bash
git clone <repo>
cd tinkoff_bot
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -e .
```

Для разработки и тестов:

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Конфигурация

1. **Секреты** — задайте через файл `.env` в корне проекта (скопируйте из `.env.example`):

   - `TINKOFF_TOKEN` — API-токен Тинькофф Инвестиций
   - `TINKOFF_ACCOUNT_ID` — ID счёта (для песочницы может подставиться автоматически)
   - `TELEGRAM_TOKEN` — токен бота Telegram
   - `TELEGRAM_ADMIN_CHAT_ID` — ID чата, с которого разрешено управление

   Опционально: `OPENROUTER_API_KEY` (LLM и macro-советник), `FINAM_API_TOKEN`, `SANDBOX_TARGET_CASH`, `DRY_RUN=true`.

2. **config.yaml** — режим, портфель, риски, инструменты. Все параметры подписаны в файле. Режим `mode: sandbox` или `mode: real` (в real ужесточаются лимиты рисков).

## Docker и деплой на VPS

- Сборка и запуск: `docker compose up -d` (перед этим создайте `.env` из `.env.example`).
- Health-check: `curl http://localhost:8000/health`
- Проверка API: `python scripts/check_apis.py`
- Push в `main` → автодеплой на VPS (GitHub Actions, secrets `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`).
- Подробно: [DEPLOY.md](DEPLOY.md).

## Запуск

- **Торговый робот:**  
  `python run_bot.py`  
  В **sandbox** с `ops.auto_start_sandbox: true` торговля стартует сама после перезапуска. Иначе нажмите **Старт** в Telegram. **СТОП** — пауза; выход — Ctrl+C.

- **Обучение RL-моделей:**  
  `python train_rl.py --figi BBG004730ZJ9 --days 365 --out data/rl_model.zip --timesteps 50000`  
  Опции: `--commission`, `--walk-forward`, `--tune` (подбор гиперпараметров Optuna).

- **Самообучение (подбор параметров стратегий):**  
  Через Telegram команду «Переобучить» или вызов `run_retrain` из кода.

## Команды Telegram

| Команда / кнопка | Описание |
|------------------|----------|
| Старт | Запуск торговли (ребаланс по расписанию и дрейфу) |
| СТОП | Остановка торговли (пауза), повторный Старт — снова запуск |
| Статус | Режим, dry-run, портфель, просадка, следующее время ребаланса/дайджеста |
| Портфель | Целевые веса и текущие отклонения |
| Ребаланс | Разовый ребаланс (с учётом окна и подтверждения в real) |
| Помощь | Список команд и время работы робота |
| /last_errors | Последние записи из лога с ошибками |
| Пауза 1 ч / 24 ч | Временная пауза торговли |
| /unpause \<тикер\> | Снять паузу по инструменту |

В режиме **real** при первом ребалансе потребуется ответ «Да» для подтверждения; при нажатии СТОП — повторное подтверждение.

## Режимы: sandbox и real

- **sandbox** — торговля в песочнице Тинькофф, баланс можно задать через `SANDBOX_TARGET_CASH`.
- **real** — боевой счёт: автоматически ужесточаются лимиты просадки и дневного убытка, ограничиваются доли позиций; для ребаланса и СТОП нужно подтверждение в чате.

## Резервное копирование

Перед обновлением или для сохранения состояния рекомендуется делать бэкап:

- **data/** — логи (`data/logs/`), алерты (`data/alerts.log`), состояние риска, кэш, RL-модели (`data/*.zip`, `data/*.json`), история сделок, last_trades, position_peaks.
- **learned_params/** — подобранные параметры стратегий (`params.json`).

Пример (Windows PowerShell):

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmm"
Compress-Archive -Path data, learned_params -DestinationPath "backup_$ts.zip"
```

Пример (Linux/macOS):

```bash
tar -czvf backup_$(date +%Y%m%d_%H%M).tar.gz data learned_params
```

Скрипт в репозитории: `python scripts/backup_data.py` — создаёт в корне проекта архив `backup_YYYYMMDD_HHMM.zip`. Рекомендуется настроить периодический бэкап (cron/Task Scheduler) или делать его перед деплоем.

## Мониторинг

- **Health-check:** HTTP `GET http://<host>:<port>/health` — возвращает 200 и JSON с полями `broker_ok`, `config_ok`, `ready`. Порт задаётся в `config.yaml` (секция `web`).
- **Метрики Prometheus:** `GET http://<host>:<port>/metrics` — счётчики и гаужи (equity, drawdown, сделки, ошибки). Используйте тот же порт, что и для health.

## Тесты

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

При деплое в git на каждый push в `main` запускаются pytest (локально) и GitHub Actions deploy на VPS.
