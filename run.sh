#!/bin/bash

# ============================================
# VideoEditor - Скрипт запуска для Linux/macOS
# ============================================

echo "Запуск Video Editor..."
echo ""

python main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "Ошибка при запуске приложения!"
    echo "Убедитесь, что установлены все зависимости:"
    echo "  pip install -r requirements.txt"
    echo ""
fi
