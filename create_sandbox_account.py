import requests
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv('TINKOFF_TOKEN_SANDBOX')
print(f"🔑 Токен: {token[:10]}...{token[-10:]}")

# URL для создания счета в песочнице
url = "https://sandbox-invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.SandboxService/OpenSandboxAccount"

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print("\n📝 Создаем счет в песочнице...")
response = requests.post(url, headers=headers, json={})

if response.status_code == 200:
    data = response.json()
    account_id = data.get('accountId')
    print(f"✅ Счет успешно создан!")
    print(f"🆔 Account ID: {account_id}")
    
    # Сохраняем ID в файл для будущего использования
    with open('sandbox_account.txt', 'w') as f:
        f.write(account_id)
    print("📁 Account ID сохранен в sandbox_account.txt")
    
elif response.status_code == 409:
    print("⚠️ Счет уже существует (код 409)")
    # Пробуем получить список счетов
    url_list = "https://sandbox-invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"
    response_list = requests.post(url_list, headers=headers, json={})
    if response_list.status_code == 200:
        accounts = response_list.json().get('accounts', [])
        if accounts:
            print(f"✅ Найдены счета: {accounts}")
            with open('sandbox_account.txt', 'w') as f:
                f.write(accounts[0]['id'])
else:
    print(f"❌ Ошибка: {response.status_code}")
    print(f"Ответ: {response.text}")