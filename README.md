# Tinkoff Trading Bot

Робот для автоматического ребаланса портфеля по стратегиям (RL, momentum, mean reversion и др.) с интеграцией Тинькофф Инвестиций и Telegram.

## Требования

- Python 3.10+
- Токены: Тинькофф Инвестиции (API), Telegram Bot

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

   Опционально: `SANDBOX_TARGET_CASH` (целевой баланс в рублях в песочнице), `DRY_RUN=true` (без реальных заявок).

2. **config.yaml** — режим, портфель, риски, инструменты. Все параметры подписаны в файле. Режим `mode: sandbox` или `mode: real` (в real ужесточаются лимиты рисков).

## Docker и деплой на VPS

- Сборка и запуск в контейнере: `docker compose up -d` (перед этим создайте `.env` из `.env.example`).
- Полная инструкция по переносу в Git, сборке образа и деплою на VPS (в т.ч. [U1 Host](https://u1host.com/ru)) — в [DEPLOY.md](DEPLOY.md).

## Запуск

- **Торговый робот:**  
  `python run_bot.py`  
  После запуска откройте Telegram, нажмите **Старт** — начнутся ребаланс и мониторинг. **СТОП** ставит паузу (процесс не завершается); полный выход — Ctrl+C.

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

При деплое в git можно добавить CI (например, GitHub Actions), который запускает эти тесты на каждый push/PR.
