import requests
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv('TINKOFF_TOKEN_SANDBOX')
print(f"Токен: {token[:10]}...{token[-10:] if token else 'None'}")

# Прямой запрос к API песочницы
url = "https://sandbox-invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print(f"\n🔍 Прямой запрос к API:")
response = requests.post(url, headers=headers, json={})
print(f"Статус: {response.status_code}")

if response.status_code == 200:
    print("✅ Токен работает!")
    print(f"Ответ: {response.json()}")
elif response.status_code == 401:
    print("❌ Токен недействителен (401)")
    print(f"Ответ: {response.text}")
else:
    print(f"⚠️ Другой статус: {response.status_code}")
    print(f"Ответ: {response.text}")