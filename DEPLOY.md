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

На сервере:

```bash
cd /opt/tinkoff_bot
git pull
docker compose build
docker compose up -d
```

---

## 5. Важно

- На сервере должен быть **один** запущенный контейнер бота (иначе конфликт Telegram getUpdates).
- Файлы `data/` и `learned_params/` монтируются с хоста — логи и обученные параметры сохраняются между перезапусками.
- Порт 8000 используется для health-check; при необходимости измените в `config.yaml` (секция `web`) и в `docker-compose.yml` (ports).
