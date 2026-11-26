@echo off
setlocal
cd /d "%~dp0"
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
set "VIDEO_EDITOR_PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "VIDEO_EDITOR_PYTHON=%~dp0.venv\Scripts\python.exe"
"%VIDEO_EDITOR_PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не установлен или не в PATH!
    echo Скачайте Python с https://www.python.org/
    pause
    exit /b 1
)
echo Python найден: 
"%VIDEO_EDITOR_PYTHON%" --version

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
"%VIDEO_EDITOR_PYTHON%" -m pip install -r requirements.txt
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
"%VIDEO_EDITOR_PYTHON%" create_shortcut.py
if errorlevel 1 (
    echo Не удалось создать ярлык. Для запуска используйте run.bat.
) else (
    echo Для запуска откройте ярлык Video Editor в папке проекта.
)
echo.
pause
