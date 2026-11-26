"""
История операций и статистика Video Editor
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict


class OperationHistory:
    """Класс для сохранения истории операций"""
    
    HISTORY_FILE = "operation_history.json"
    
    def __init__(self):
        self.history: List[Dict] = []
        self.load_history()
    
    def load_history(self):
        """Загружает историю из файла"""
        if Path(self.HISTORY_FILE).exists():
            try:
                with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
            except Exception as e:
                print(f"Ошибка при загрузке истории: {e}")
                self.history = []
    
    def save_history(self):
        """Сохраняет историю в файл"""
        try:
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении истории: {e}")
    
    def add_operation(self, input_file: str, output_file: str, 
                     start_time: float, end_time: float, 
                     success: bool, error_message: str = None):
        """Добавляет операцию в историю"""
        operation = {
            "timestamp": datetime.now().isoformat(),
            "input_file": input_file,
            "output_file": output_file,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
            "success": success,
            "error_message": error_message
        }
        self.history.append(operation)
        self.save_history()
    
    def get_statistics(self) -> Dict:
        """Получает статистику операций"""
        total = len(self.history)
        successful = sum(1 for op in self.history if op['success'])
        failed = total - successful
        total_duration_trimmed = sum(op['duration'] for op in self.history if op['success'])
        
        return {
            "total_operations": total,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / total * 100) if total > 0 else 0,
            "total_duration_trimmed_minutes": total_duration_trimmed / 60
        }
    
    def get_last_operations(self, count: int = 10) -> List[Dict]:
        """Получает последние операции"""
        return self.history[-count:]
    
    def clear_history(self):
        """Очищает историю"""
        self.history = []
        self.save_history()


# Глобальный экземпляр истории
history = OperationHistory()
