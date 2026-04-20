"""Secure logging with rotation"""

import logging
import os
from logging.handlers import RotatingFileHandler

class SecureLogger:
    """Thread-safe logger with rotation and context"""
    
    def __init__(self, name: str, log_path: str, level=logging.INFO):
        self.name = name
        self.log_path = log_path
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        # Create log directory
        os.makedirs(log_path, exist_ok=True)
        
        # File handler with rotation (10 MB per file, 5 backups)
        log_file = os.path.join(log_path, f"{name}.log")
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def info(self, msg: str, **kwargs):
        self.logger.info(msg, extra=kwargs)
    
    def warning(self, msg: str, **kwargs):
        self.logger.warning(msg, extra=kwargs)
    
    def error(self, msg: str, **kwargs):
        self.logger.error(msg, extra=kwargs)
    
    def debug(self, msg: str, **kwargs):
        self.logger.debug(msg, extra=kwargs)
    
    def trade(self, ticker: str, action: str, price: float, quantity: float):
        """Log a trade with special format"""
        self.logger.info(
            f"TRADE|{ticker}|{action}|{price:.2f}|{quantity:.4f}"
        )