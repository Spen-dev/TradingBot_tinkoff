from TinvestPy import TinvestPy
from dotenv import load_dotenv
import os

load_dotenv()

token = os.getenv('TINKOFF_TOKEN_SANDBOX')
print(f"🔑 Токен: {token[:10]}...{token[-10:]}")

try:
    # Шаг 1: Просто создаем клиента
    print("\n1️⃣ Создаем клиента...")
    client = TinvestPy(token)
    print("✅ Клиент создан")
    
    # Шаг 2: Проверяем методы
    print("\n2️⃣ Доступные методы:")
    methods = [m for m in dir(client) if not m.startswith('_')]
    for m in methods[:10]:  # Покажем первые 10 методов
        print(f"   • {m}")
    
    print(f"\n   ... и еще {len(methods)-10} методов")
    
except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    
    # Анализируем ошибку
    error_str = str(e)
    if 'accounts' in error_str:
        print("\n🔍 Диагноз: TinvestPy пытается получить счета")
        print("Решение: Нужно создать счет в песочнице")