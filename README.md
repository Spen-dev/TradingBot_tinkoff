# 🤖 AI Trading Bot

Профессиональный торговый бот с искусственным интеллектом для Т-Инвестиций.

## 🚀 Возможности

- **Поддержка песочницы** для безопасного тестирования
- **AI/ML предсказания**: LSTM + XGBoost
- **Автоматическая ребалансировка** портфеля
- **Резервный источник** данных (MOEX)
- **Telegram мониторинг** 24/7
- **Docker контейнеризация**
- **CI/CD через GitHub Actions**
- **Налоговый учет**
- **Rate limiting защита**
- **Кэширование и БД**

## 📊 Портфель

| Тикер | Компания | Доля |
|-------|----------|------|
| YDEX | Яндекс | 17% |
| SBER | Сбербанк | 17% |
| T | Т-Технологии | 13% |
| TRNFP | Транснефть ап | 10% |
| OZON | Ozon | 10% |
| PLZL | Полюс | 7% |
| SU26238RMFS4 | ОФЗ 26238 | 13% |
| SU26240RMFS0 | ОФЗ 26240 | 13% |

## 🛠 Установка

### Локальная разработка

```bash
# Клонировать репозиторий
git clone https://github.com/yourusername/trading-bot.git
cd trading-bot

# Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Установить зависимости
pip install -r requirements.txt

# Настроить .env
cp .env.example .env
# Отредактируйте .env с вашими токенами

# Запустить
python -m src.bot

cd docker
docker-compose up -d
docker-compose logs -f

🤖 Telegram команды
/start - Приветствие
/status - Состояние портфеля
/trades - Последние сделки
/tax - Налоговый отчет
/help - Помощь