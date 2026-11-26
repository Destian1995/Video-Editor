"""
Анализ и оптимизация видео
"""

import ffmpeg
import json
from typing import Dict, List


class VideoAnalyzer:
    """Класс для глубокого анализа видео файлов"""
    
    @staticmethod
    def get_detailed_info(video_path: str) -> Dict:
        """Получает детальную информацию о видео"""
        try:
            probe = ffmpeg.probe(video_path)
            
            # Общая информация
            format_info = probe['format']
            
            # Видео поток
            video_stream = next(
                (s for s in probe['streams'] if s['codec_type'] == 'video'),
                None
            )
            
            # Аудио поток
            audio_stream = next(
                (s for s in probe['streams'] if s['codec_type'] == 'audio'),
                None
            )
            
            return {
                "format": {
                    "filename": format_info.get('filename'),
                    "duration": float(format_info.get('duration', 0)),
                    "size_mb": float(format_info.get('size', 0)) / (1024 * 1024),
                    "bit_rate": format_info.get('bit_rate'),
                    "format_name": format_info.get('format_name'),
                },
                "video": VideoAnalyzer._extract_video_info(video_stream) if video_stream else None,
                "audio": VideoAnalyzer._extract_audio_info(audio_stream) if audio_stream else None,
            }
        except Exception as e:
            raise Exception(f"Ошибка при анализе видео: {str(e)}")
    
    @staticmethod
    def _extract_video_info(stream: Dict) -> Dict:
        """Извлекает информацию о видео потоке"""
        return {
            "codec": stream.get('codec_name'),
            "codec_long": stream.get('codec_long_name'),
            "width": stream.get('width'),
            "height": stream.get('height'),
            "fps": eval(stream.get('r_frame_rate', '30/1')),
            "bit_rate": stream.get('bit_rate'),
            "color_space": stream.get('color_space'),
            "profile": stream.get('profile'),
            "level": stream.get('level'),
            "duration": float(stream.get('duration', 0)),
        }
    
    @staticmethod
    def _extract_audio_info(stream: Dict) -> Dict:
        """Извлекает информацию об аудио потоке"""
        return {
            "codec": stream.get('codec_name'),
            "codec_long": stream.get('codec_long_name'),
            "sample_rate": stream.get('sample_rate'),
            "channels": stream.get('channels'),
            "channel_layout": stream.get('channel_layout'),
            "bit_rate": stream.get('bit_rate'),
            "duration": float(stream.get('duration', 0)),
        }
    
    @staticmethod
    def estimate_output_size(input_path: str, start_time: float, end_time: float) -> Dict:
        """Оценивает размер выходного файла"""
        try:
            probe = ffmpeg.probe(input_path)
            format_info = probe['format']
            video_stream = next(
                (s for s in probe['streams'] if s['codec_type'] == 'video'),
                None
            )
            
            if not video_stream:
                raise ValueError("Видео поток не найден")
            
            duration = float(format_info.get('duration', 0))
            total_size = float(format_info.get('size', 0))
            trim_duration = end_time - start_time
            
            # При stream copy размер примерно пропорционален длительности
            estimated_size = (total_size * trim_duration / duration) if duration > 0 else 0
            
            return {
                "original_size_mb": total_size / (1024 * 1024),
                "original_duration": duration,
                "trim_duration": trim_duration,
                "estimated_output_mb": estimated_size / (1024 * 1024),
                "compression_ratio": (estimated_size / total_size * 100) if total_size > 0 else 0,
            }
        except Exception as e:
            raise Exception(f"Ошибка при оценке размера: {str(e)}")


class VideoOptimizer:
    """Класс для оптимизации видео"""
    
    @staticmethod
    def suggest_settings(video_info: Dict) -> Dict:
        """Рекомендует оптимальные настройки для видео"""
        suggestions = {
            "codec": "h264",
            "preset": "fast",
            "quality": "medium",
            "keep_audio": True,
        }
        
        # Если видео очень большое, рекомендуем быстрый preset
        if video_info.get('format', {}).get('size_mb', 0) > 1000:
            suggestions["preset"] = "ultrafast"
        
        # Если разрешение высокое, рекомендуем меньший битрейт
        if video_info.get('video', {}).get('width', 0) >= 1920:
            suggestions["quality"] = "high"
        
        return suggestions
    
    @staticmethod
    def get_stream_copy_compatibility(video_info: Dict) -> Dict:
        """Проверяет совместимость видео для stream copy обрезки"""
        compatibility = {
            "is_compatible": True,
            "issues": [],
            "warnings": []
        }
        
        video = video_info.get('video')
        if not video:
            compatibility["is_compatible"] = False
            compatibility["issues"].append("Видео поток не найден")
            return compatibility
        
        # Проверяем кодек
        supported_codecs = ['h264', 'hevc', 'mpeg4', 'vp8', 'vp9']
        if video.get('codec') not in supported_codecs:
            compatibility["warnings"].append(
                f"Кодек {video.get('codec')} может быть несовместим"
            )
        
        return compatibility
