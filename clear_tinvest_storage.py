import keyring
import os

# Названия, которые TinvestPy использует для хранения
SERVICE_NAMES = ['TinvestPy', 'TinvestPy_token', 'tinvestpy_token']

for service in SERVICE_NAMES:
    try:
        keyring.delete_password(service, 'token')
        print(f"✅ Удалён токен из {service}")
    except:
        print(f"ℹ️ Токен не найден в {service}")

print("\n✅ Хранилище очищено. Теперь можно передать новый токен.")