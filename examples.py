"""
Примеры использования Video Editor
"""

from video_processor import VideoProcessor
from video_analyzer import VideoAnalyzer, VideoOptimizer
from pathlib import Path


def example_1_basic_trim():
    """Пример 1: Базовая обрезка видео"""
    print("\n=== Пример 1: Базовая обрезка ===")
    
    processor = VideoProcessor()
    
    # Замените на путь вашего видео
    video_path = "example.mp4"
    output_path = "trimmed_example.mp4"
    
    try:
        # Загружаем информацию о видео
        info = processor.load_video_info(video_path)
        print(f"Видео: {info['width']}x{info['height']}")
        print(f"Длительность: {processor.format_time(info['duration'])}")
        print(f"FPS: {info['fps']}")
        
        # Обрезаем видео (с 10 до 60 секунд)
        print("\nОбрезание видео...")
        processor.trim_video(video_path, output_path, 10, 60)
        print("✅ Готово!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def example_2_detailed_analysis():
    """Пример 2: Детальный анализ видео"""
    print("\n=== Пример 2: Детальный анализ ===")
    
    video_path = "example.mp4"
    
    try:
        analyzer = VideoAnalyzer()
        
        # Получаем детальную информацию
        info = analyzer.get_detailed_info(video_path)
        
        print("\n📹 Формат:")
        for key, value in info['format'].items():
            print(f"  {key}: {value}")
        
        if info['video']:
            print("\n🎬 Видео поток:")
            for key, value in info['video'].items():
                print(f"  {key}: {value}")
        
        if info['audio']:
            print("\n🔊 Аудио поток:")
            for key, value in info['audio'].items():
                print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def example_3_size_estimation():
    """Пример 3: Оценка размера выходного файла"""
    print("\n=== Пример 3: Оценка размера ===")
    
    video_path = "example.mp4"
    
    try:
        analyzer = VideoAnalyzer()
        
        # Оцениваем размер при обрезке с 10 до 60 секунд
        estimation = analyzer.estimate_output_size(video_path, 10, 60)
        
        print(f"Исходный размер: {estimation['original_size_mb']:.2f} МБ")
        print(f"Исходная длительность: {estimation['original_duration']:.2f} сек")
        print(f"Длительность обрезки: {estimation['trim_duration']:.2f} сек")
        print(f"Ожидаемый размер: {estimation['estimated_output_mb']:.2f} МБ")
        print(f"Сжатие: {estimation['compression_ratio']:.1f}%")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def example_4_compatibility_check():
    """Пример 4: Проверка совместимости для stream copy"""
    print("\n=== Пример 4: Проверка совместимости ===")
    
    video_path = "example.mp4"
    
    try:
        analyzer = VideoAnalyzer()
        
        # Получаем информацию и проверяем совместимость
        info = analyzer.get_detailed_info(video_path)
        compatibility = VideoOptimizer.get_stream_copy_compatibility(info)
        
        if compatibility['is_compatible']:
            print("✅ Видео совместимо с быстрой обрезкой (stream copy)")
        else:
            print("❌ Видео может быть несовместимо:")
            for issue in compatibility['issues']:
                print(f"  - {issue}")
        
        if compatibility['warnings']:
            print("\n⚠️ Предупреждения:")
            for warning in compatibility['warnings']:
                print(f"  - {warning}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def example_5_optimize_settings():
    """Пример 5: Получение оптимальных настроек"""
    print("\n=== Пример 5: Оптимальные настройки ===")
    
    video_path = "example.mp4"
    
    try:
        analyzer = VideoAnalyzer()
        
        # Получаем информацию
        info = analyzer.get_detailed_info(video_path)
        
        # Получаем рекомендации
        suggestions = VideoOptimizer.suggest_settings(info)
        
        print("\n💡 Рекомендуемые настройки:")
        for key, value in suggestions.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    print("Video Editor - Примеры использования")
    print("=====================================")
    
    # Раскомментируйте примеры для тестирования
    # example_1_basic_trim()
    # example_2_detailed_analysis()
    # example_3_size_estimation()
    # example_4_compatibility_check()
    # example_5_optimize_settings()
    
    print("\n📝 Используйте эти примеры как шаблоны для своего кода")
