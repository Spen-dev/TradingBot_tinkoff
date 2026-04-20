import os
import site
import sys

def patch_tinvestpy():
    """Патчит TinvestPy для работы с пустыми счетами"""
    
    # Находим путь к TinvestPy
    for path in site.getsitepackages():
        file_path = os.path.join(path, 'TinvestPy', 'TinvestPy.py')
        if os.path.exists(file_path):
            print(f"Найден TinvestPy: {file_path}")
            
            # Читаем файл
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Заменяем проблемный метод
            old_code = """    def get_info(self):
        \"\"\"Получение информации о счетах\"\"\"
        accounts_data = self._make_request('GetAccounts', {})
        return accounts_data"""
            
            new_code = """    def get_info(self):
        \"\"\"Получение информации о счетах (с поддержкой пустых счетов)\"\"\"
        try:
            accounts_data = self._make_request('GetAccounts', {})
            if not accounts_data or 'accounts' not in accounts_data:
                return {'accounts': [], 'tariff': 'sandbox', 'qualified': False}
            return accounts_data
        except Exception as e:
            return {'accounts': [], 'tariff': 'sandbox', 'qualified': False, 'error': str(e)}"""
            
            if old_code in content:
                content = content.replace(old_code, new_code)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print("✅ TinvestPy успешно пропатчен!")
                return True
            else:
                print("⚠️ Код не найден, возможно другая версия")
                return False
    
    print("❌ TinvestPy не найден")
    return False

if __name__ == "__main__":
    patch_tinvestpy()