import os
import site

def patch_tinvestpy():
    """Радикальный патч TinvestPy - полностью отключаем проверку счетов"""
    
    # Находим файл
    for path in site.getsitepackages():
        filepath = os.path.join(path, 'TinvestPy', 'TinvestPy.py')
        if os.path.exists(filepath):
            print(f"✅ Найден TinvestPy: {filepath}")
            
            # Читаем файл
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Полностью заменяем __init__ метод
            import re
            
            # Находим метод __init__
            pattern = r'def __init__\(self, token,.*?\):.*?(?=def|\Z)'
            init_method = re.search(pattern, content, re.DOTALL)
            
            if init_method:
                print("🔍 Найден метод __init__, создаем патч...")
                
                # Создаем новый __init__ метод без проверки счетов
                new_init = '''def __init__(self, token, subscriptions_portfolio_handler=None, subscriptions_positions_handler=None, subscriptions_trades_handler=None, subscriptions_marketdata_handler=None, subscriptions_order_state_handler=None, call_function=None, server='invest-public-api.tinkoff.ru', server_demo='sandbox-invest-public-api.tinkoff.ru'):
        """
        Инициализация клиента Tinkoff API
        
        :param token: str - токен доступа
        """
        self.token = token
        self.server = server
        self.server_demo = server_demo
        self.channel = None
        self.metadata = None
        
        # Создаем пустые обработчики подписок
        self.subscriptions_portfolio_handler = subscriptions_portfolio_handler
        self.subscriptions_positions_handler = subscriptions_positions_handler
        self.subscriptions_trades_handler = subscriptions_trades_handler
        self.subscriptions_marketdata_handler = subscriptions_marketdata_handler
        self.subscriptions_order_state_handler = subscriptions_order_state_handler
        self.call_function = call_function
        
        # Устанавливаем режим песочницы
        self.use_sandbox = True
        
        # Создаем пустой список счетов (чтобы не падало)
        self.accounts = []
        self.account_id = 'sandbox_default'
        
        # Устанавливаем временную зону
        import zoneinfo
        self.tz_msk = zoneinfo.ZoneInfo('Europe/Moscow')'''
                
                # Заменяем старый метод новым
                content = content.replace(init_method.group(), new_init)
                
                # Сохраняем изменения
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                print("✅ TinvestPy успешно пропатчен!")
                return True
    
    print("❌ TinvestPy не найден")
    return False

if __name__ == "__main__":
    patch_tinvestpy()