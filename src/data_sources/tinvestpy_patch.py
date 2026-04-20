"""Обёртка для TinvestPy, отключающая проверку счетов"""

import types
import sys

def patch_tinvestpy():
    """Патчит TinvestPy на лету"""
    
    try:
        import TinvestPy
        original_init = TinvestPy.TinvestPy.__init__
        
        def patched_init(self, token, *args, **kwargs):
            # Вызываем оригинальный __init__
            original_init(self, token, *args, **kwargs)
            # Но подменяем accounts на пустой список, чтобы не падало
            self.accounts = []
            self.account_id = 'sandbox_default'
        
        # Подменяем метод
        TinvestPy.TinvestPy.__init__ = patched_init
        
        print("✅ TinvestPy успешно пропатчен для песочницы")
        return True
    except Exception as e:
        print(f"❌ Ошибка патча: {e}")
        return False

# Применяем патч при импорте
patch_tinvestpy()