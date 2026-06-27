# Деплой робота на VPS (U1 Host и др.)

## 1. Репозиторий Git

На своей машине (если ещё не сделано):

```bash
cd tinkoff_bot
git init
git add .
git commit -m "Initial: trading bot + Docker"
git remote add origin <URL вашего репо на GitHub/GitLab>
git push -u origin main
```

Секреты в `.env` в репозиторий не попадают (см. `.gitignore`). На сервер `.env` нужно создать вручную или скопировать отдельно.

---

## 2. Сервер (U1 Host)

1. Заказать VPS на [U1 Host](https://u1host.com/ru): Ubuntu 22.04 или Debian 12, от 1 ГБ RAM.
2. Подключиться по SSH:
   ```bash
   ssh root@<IP_сервера>
   ```
3. Установить Docker и Docker Compose:
   ```bash
   apt update && apt install -y docker.io docker-compose-v2
   systemctl enable --now docker
   ```

---

## 3. Клонирование и запуск на сервере

```bash
cd /opt
git clone <URL вашего репо> tinkoff_bot
cd tinkoff_bot
```

Создать `.env` с теми же переменными, что и локально:

```bash
nano .env
# TINKOFF_TOKEN=...
# TINKOFF_ACCOUNT_ID=...
# TELEGRAM_TOKEN=...
# TELEGRAM_ADMIN_CHAT_ID=...
# SANDBOX_TARGET_CASH=120000
# OPENROUTER_API_KEY=...   # опционально: LLM-советник через OpenRouter (стратегия ai)
```

Собрать образ и запустить:

```bash
docker compose build
docker compose up -d
```

Проверка:

```bash
docker compose ps
curl -s http://localhost:8000/health
```

Логи:

```bash
docker compose logs -f bot
```

---

## 4. Обновление после изменений в Git

### Вручную на сервере

```bash
cd /opt/TradingBot_tinkoff
git pull
docker compose build
docker compose up -d
```

### Автоматически (GitHub Actions)

При push в `main` workflow `.github/workflows/deploy.yml` подключается по SSH и пересобирает контейнер.

**Secrets в репозитории GitHub** (Settings → Secrets and variables → Actions):

| Secret | Значение |
|--------|----------|
| `VPS_HOST` | `YOUR_VPS_IP` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | приватный ключ SSH (`~/.ssh/id_ed25519`) |

**Быстрая настройка** (после `gh auth login`):

```powershell
.\scripts\setup_github_secrets.ps1
```

Скрипт добавит secrets и обновит описание репозитория на GitHub.

На сервере репозиторий должен лежать в `/opt/TradingBot_tinkoff` (как в workflow).

---

## 5. Автоматизация (ops)

В `config.yaml` секция `ops`:

- **auto_start_sandbox** — после перезапуска Docker бот сам нажимает «Старт» (sandbox).
- **block_trading_on_config_error** — при ошибках конфига торговля блокируется, но мониторинг работает.
- **exit_on_config_error_real** — в режиме `real` процесс завершается (Docker перезапустит).
- **openrouter_balance_check_hours** — алерт при низком балансе OpenRouter.
- **macro_refresh_on_news_change / macro_refresh_on_index_drop_pct** — вне 7-дн. цикла обновление портfеля по новостям или падению индекса.
- **learned_params_backup_interval_hours** — копии в `data/backups/`.
- **watchdog_exit_after_failures** — при сбоях брокера выход для `restart: unless-stopped`.

Health-check Docker: `GET http://localhost:8000/health` (503 при ошибках конфига или брокера).

---

## 6. Важно

- На сервере должен быть **один** запущенный контейнер бота (иначе конфликт Telegram getUpdates).
- Файлы `data/` и `learned_params/` монтируются с хоста — логи и обученные параметры сохраняются между перезапусками.
- Порт 8000 используется для health-check; при необходимости измените в `config.yaml` (секция `web`) и в `docker-compose.yml` (ports).

---

## 7. Бот не отвечает в Telegram

1. **Проверить, что контейнер запущен и не падает:**
   ```bash
   docker compose ps
   docker compose logs -f bot
   ```
   В логах должна быть строка: `Telegram polling запущен; ответы только в чате admin_chat_id=...` — если её нет, процесс падает до старта polling (ошибка конфига, брокера или импорта).

2. **В `.env` на сервере обязательны:**
   - `TELEGRAM_TOKEN` — токен бота от @BotFather
   - `TELEGRAM_ADMIN_CHAT_ID` — **числовой** id чата, с которого разрешены команды (бот отвечает только этому чату).

3. **Узнать свой chat_id:** напишите боту @userinfobot в Telegram — он пришлёт ваш id. Этот же id укажите в `TELEGRAM_ADMIN_CHAT_ID` и пишите боту **из того же аккаунта** (личный чат с ботом или группа, где id совпадает).

4. **Проверить переменные в контейнере:**
   ```bash
   docker compose exec bot env | grep TELEGRAM
   ```
   Должны быть непустые `TELEGRAM_TOKEN` и `TELEGRAM_ADMIN_CHAT_ID`.
