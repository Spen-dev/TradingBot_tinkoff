from TinvestPy import TinvestPy
from dotenv import load_dotenv
import os

load_dotenv()

token = os.getenv('TINKOFF_TOKEN_SANDBOX')

# Читаем Account ID
try:
    with open('account_id.txt', 'r') as f:
        account_id = f.read().strip()
except:
    print("❌ Сначала создайте счет: python create_account.py")
    exit()

print(f"🔑 Токен: {token[:10]}...{token[-10:]}")
print(f"🆔 Account ID: {account_id}")

try:
    # Создаем клиента
    print("\n1️⃣ Создаем клиента...")
    client = TinvestPy(token)
    print("✅ Клиент создан")
    
    # Пытаемся получить портфель
    print("\n2️⃣ Получаем портфель...")
    try:
        portfolio = client.get_portfolio()
        print(f"✅ Портфель получен: {portfolio}")
    except Exception as e:
        print(f"❌ Ошибка get_portfolio: {e}")
    
    # Пытаемся получить информацию об инструменте
    print("\n3️⃣ Получаем информацию о SBER...")
    try:
        if hasattr(client, 'get_symbol_info'):
            info = client.get_symbol_info('SBER')
            print(f"✅ Информация: {info}")
        else:
            print("ℹ️ Метод get_symbol_info не найден")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
except Exception as e:
    print(f"\n❌ Общая ошибка: {e}")