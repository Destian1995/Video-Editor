@echo off
REM ============================================
REM VideoEditor - Скрипт установки для Windows
REM ============================================

echo.
echo ========================================
echo Установка Video Editor
echo ========================================
echo.

REM Проверка Python
echo [1/3] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не установлен или не в PATH!
    echo Скачайте Python с https://www.python.org/
    pause
    exit /b 1
)
echo Python найден: 
python --version

REM Проверка FFmpeg
echo.
echo [2/3] Проверка FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: FFmpeg не установлен или не в PATH!
    echo Скачайте FFmpeg с https://ffmpeg.org/download.html
    echo Или установите через Chocolatey: choco install ffmpeg
    pause
    exit /b 1
)
echo FFmpeg найден!

REM Установка зависимостей
echo.
echo [3/3] Установка Python зависимостей...
pip install -r requirements.txt
if errorlevel 1 (
    echo Ошибка при установке зависимостей!
    pause
    exit /b 1
)

echo.
echo ========================================
echo Установка успешна!
echo ========================================
echo.
echo Для запуска приложения выполните:
echo   python main.py
echo.
pause
