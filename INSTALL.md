# Установка Video Editor

## 🖥️ Требования

- Python 3.8 или выше
- FFmpeg
- ОС: Windows, Linux или macOS

## ⚙️ Пошаговая установка

### Шаг 1: Установка Python

Если у вас еще не установлен Python:

1. Перейдите на [python.org](https://www.python.org/downloads/)
2. Скачайте Python 3.11 или выше
3. **ВАЖНО:** При установке отметьте "Add Python to PATH"
4. Завершите установку

Проверьте установку:
```bash
python --version
```

### Шаг 2: Установка FFmpeg

#### Windows

**Способ 1: Через Chocolatey (рекомендуется)**
```bash
choco install ffmpeg
```

**Способ 2: Ручная установка**
1. Перейдите на [ffmpeg.org/download.html](https://ffmpeg.org/download.html)
2. Скачайте Windows Build
3. Распакуйте архив в `C:\ffmpeg`
4. Добавьте `C:\ffmpeg\bin` в PATH:
   - Нажмите `Win + X` → System
   - Advanced System Settings
   - Environment Variables
   - Добавьте путь к ffmpeg\bin

Проверьте установку:
```bash
ffmpeg -version
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

#### macOS

```bash
brew install ffmpeg
```

### Шаг 3: Установка Python зависимостей

#### Быстрый способ (все системы)

1. Откройте командную строку в папке проекта
2. Запустите установку:

**Windows:**
```bash
install.bat
```

**Linux/macOS:**
```bash
chmod +x run.sh
pip install -r requirements.txt
```

#### Ручной способ

```bash
pip install PyQt5==5.15.9
pip install ffmpeg-python==0.2.1
pip install opencv-python==4.8.1.78
pip install Pillow==10.1.0
pip install numpy==1.24.3
```

## 🚀 Запуск приложения

### Windows

После `install.bat` откройте ярлык **Video Editor** в папке проекта. Если зависимости установлены вручную, создайте ярлык командой `python create_shortcut.py` из папки проекта. Скрипт использует локальное окружение `.venv`, если оно существует.

Для запуска без ярлыка откройте `run.bat`.

**Способ 2: Командная строка**
```bash
python main.py
```

### Linux/macOS

```bash
python main.py
```

Или:
```bash
chmod +x run.sh
./run.sh
```

## ✅ Проверка установки

Перед первым запуском приложение автоматически проверит все зависимости.

Если вы видите ошибки, выполните проверку вручную:

```bash
python check_dependencies.py
```

## 🐛 Решение проблем

### "FFmpeg not found"

**Windows:**
```bash
# Проверьте установку
ffmpeg -version

# Если не работает, переустановите FFmpeg
choco uninstall ffmpeg
choco install ffmpeg

# Или добавьте вручную в PATH
setx PATH "%PATH%;C:\ffmpeg\bin"
```

**Linux:**
```bash
sudo apt-get install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

### "No module named PyQt5"

```bash
pip install --upgrade pip
pip install PyQt5==5.15.9
```

### "No module named cv2"

```bash
pip install opencv-python==4.8.1.78
```

### Приложение не запускается

1. Проверьте версию Python:
   ```bash
   python --version  # Должно быть 3.8+
   ```

2. Проверьте зависимости:
   ```bash
   python check_dependencies.py
   ```

3. Переустановите все:
   ```bash
   pip install --upgrade -r requirements.txt
   ```

## 📝 Дополнительные команды

### Обновление зависимостей

```bash
pip install --upgrade -r requirements.txt
```

### Проверка версий пакетов

```bash
pip list
```

### Удаление и переустановка

```bash
pip uninstall PyQt5 ffmpeg-python opencv-python Pillow numpy -y
pip install -r requirements.txt
```

## 🎉 Готово!

Если все установилось успешно, запустите приложение:

```bash
python main.py
```

Возникли проблемы? Выполните:
```bash
python check_dependencies.py
```

для диагностики.
