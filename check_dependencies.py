"""
Проверка зависимостей при запуске приложения
"""

import sys

from media_process import configure_ffmpeg_path, run_media


def check_ffmpeg():
    """Проверяет установку FFmpeg"""
    try:
        result = run_media(['ffmpeg', '-version'], capture_output=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def check_python_packages():
    """Проверяет установку Python пакетов"""
    required_packages = {
        'PyQt5': 'PyQt5',
        'ffmpeg': 'ffmpeg-python',
        'cv2': 'opencv-python',
        'PIL': 'Pillow',
        'numpy': 'numpy'
    }
    
    missing_packages = []
    incompatible_opencv = False
    
    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
        except (ImportError, AttributeError) as exc:
            if import_name == 'cv2' and (
                'compiled using NumPy 1.x' in str(exc)
                or '_ARRAY_API not found' in str(exc)
            ):
                incompatible_opencv = True
            missing_packages.append(package_name)
    
    return missing_packages, incompatible_opencv


def show_error_and_exit(title: str, message: str):
    """Показывает ошибку и выходит"""
    if sys.platform == "win32" and sys.stdout is None:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
        sys.exit(1)
    print(f"\n{'='*60}")
    print(f"❌ {title}")
    print(f"{'='*60}")
    print(message)
    print(f"{'='*60}\n")
    sys.exit(1)


def check_dependencies():
    """Проверяет все зависимости"""
    configure_ffmpeg_path()
    print("Проверка зависимостей...")
    
    # Проверка FFmpeg
    if not check_ffmpeg():
        show_error_and_exit(
            "FFmpeg не установлен",
            """FFmpeg не найден в системе или не добавлен в PATH.

Установите FFmpeg:

Windows (Chocolatey):
  choco install ffmpeg

Windows (Ручная установка):
  https://ffmpeg.org/download.html

Linux (Ubuntu/Debian):
  sudo apt-get install ffmpeg

macOS:
  brew install ffmpeg

После установки убедитесь, что FFmpeg доступен в консоли:
  ffmpeg -version"""
        )
    
    # Проверка Python пакетов
    missing_packages, incompatible_opencv = check_python_packages()
    if missing_packages:
        extra_note = ""
        if incompatible_opencv:
            extra_note = (
                "\n\nПохоже, OpenCV был собран для NumPy 1.x, а в системе установлена NumPy 2.x. "
                "Установите opencv-python>=4.13.0.92 или используйте numpy<2."
            )
        show_error_and_exit(
            "Отсутствуют Python пакеты",
            f"""Следующие пакеты не установлены:
  {', '.join(missing_packages)}

Установите их командой:
  pip install -r requirements.txt

Или вручную:
  pip install {' '.join(missing_packages)}{extra_note}"""
        )
    
    print("✅ Все зависимости установлены!\n")


if __name__ == "__main__":
    check_dependencies()
