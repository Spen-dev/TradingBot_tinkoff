import requests
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv('TINKOFF_TOKEN_SANDBOX')

# Читаем Account ID
try:
    with open('sandbox_account.txt', 'r') as f:
        account_id = f.read().strip()
except:
    print("❌ Сначала запустите create_sandbox_account.py")
    exit()

print(f"🔑 Токен: {token[:10]}...{token[-10:]}")
print(f"🆔 Account ID: {account_id}")

# URL для пополнения счета
url = "https://sandbox-invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.SandboxService/SandboxPayIn"

data = {
    "accountId": account_id,
    "amount": {
        "currency": "RUB",
        "units": 15000,
        "nano": 0
    }
}

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print(f"\n💰 Пополняем счет на 15000 RUB...")
response = requests.post(url, headers=headers, json=data)

if response.status_code == 200:
    print("✅ Счет успешно пополнен!")
else:
    print(f"❌ Ошибка: {response.status_code}")
    print(f"Ответ: {response.text}")