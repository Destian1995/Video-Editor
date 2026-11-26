"""
Логирование и отладка для Video Editor
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from config import ENABLE_LOGGING, LOG_FILE


class VideoEditorLogger:
    """Логгер для приложения"""
    
    def __init__(self):
        self.logger = logging.getLogger("VideoEditor")
        self.setup_logging()
    
    def setup_logging(self):
        """Настраивает логирование"""
        if not ENABLE_LOGGING:
            return
        
        self.logger.setLevel(logging.DEBUG)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Handler для файла
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Handler для консоли
        if sys.stdout is not None:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
    
    def debug(self, message):
        self.logger.debug(message)
    
    def info(self, message):
        self.logger.info(message)
    
    def warning(self, message):
        self.logger.warning(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def critical(self, message):
        self.logger.critical(message)


# Глобальный экземпляр логгера
logger = VideoEditorLogger()
