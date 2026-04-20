from TinvestPy import TinvestPy
from dotenv import load_dotenv
import os

load_dotenv()

token = os.getenv('TINKOFF_TOKEN_SANDBOX')

# Читаем Account ID
try:
    with open('sandbox_account.txt', 'r') as f:
        account_id = f.read().strip()
    print(f"✅ Account ID загружен: {account_id}")
except:
    print("❌ Сначала создайте счет: python create_sandbox_account.py")
    exit()

try:
    # Создаем клиента
    print("\n1️⃣ Создаем клиента...")
    client = TinvestPy(token)
    
    # Принудительно устанавливаем account_id
    if hasattr(client, 'account_id'):
        client.account_id = account_id
    
    print("✅ Клиент создан")
    
    # Пробуем получить портфель
    print("\n2️⃣ Получаем портфель...")
    try:
        portfolio = client.get_portfolio()
        print(f"✅ Портфель: {portfolio}")
    except Exception as e:
        print(f"❌ Ошибка get_portfolio: {e}")
    
    # Пробуем получить цену
    print("\n3️⃣ Получаем цену SBER...")
    try:
        price = client.get_last_price('SBER')
        print(f"✅ Цена SBER: {price}")
    except Exception as e:
        print(f"❌ Ошибка get_last_price: {e}")
    
except Exception as e:
    print(f"\n❌ Общая ошибка: {e}")