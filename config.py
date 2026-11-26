"""
Конфигурация приложения Video Editor
"""

# ============ UI ============
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
WINDOW_TITLE = "Video Editor - Обрезка видео"

# Размер предпросмотра в пикселях
PREVIEW_WIDTH = 300
PREVIEW_HEIGHT = 200

# ============ Видео ============
# Поддерживаемые форматы
SUPPORTED_FORMATS = ["mp4", "avi", "mov", "mkv", "flv", "webm"]

# Качество при экспорте (если будет перекодирование)
VIDEO_CODEC = "libx264"
VIDEO_PRESET = "fast"  # ultrafast, superfast, veryfast, faster, fast, medium, slow
VIDEO_QUALITY = "medium"  # low, medium, high

AUDIO_CODEC = "aac"
AUDIO_BITRATE = "128k"

# ============ Цвета ============
PRIMARY_COLOR = "#2196F3"
PRIMARY_HOVER = "#1976D2"
PRIMARY_PRESSED = "#1565C0"
SUCCESS_COLOR = "#4CAF50"
ERROR_COLOR = "#F44336"
WARNING_COLOR = "#FF9800"

# ============ Пути ============
OUTPUT_PREFIX = "trimmed_"

# ============ Производительность ============
# Максимальный размер файла для загрузки информации (МБ)
MAX_VIDEO_SIZE_MB = 10000

# Таймаут для FFmpeg операций (секунды)
FFMPEG_TIMEOUT = 600  # 10 минут

# ============ Логирование ============
ENABLE_LOGGING = True
LOG_FILE = "video_editor.log"
