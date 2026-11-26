import ffmpeg
import cv2
import json
import os
from fractions import Fraction

from media_process import run_media


class VideoProcessor:
    """Класс для обработки видео файлов"""
    
    def __init__(self):
        self.current_video = None
        self.video_info = {}
    
    def load_video_info(self, video_path: str) -> dict:
        """Загружает информацию о видео (продолжительность, разрешение, FPS)"""
        try:
            result = run_media(
                ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", video_path],
                capture_output=True,
            )
            if result.returncode:
                raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
            probe = json.loads(result.stdout)
            video_info = next(
                (stream for stream in probe['streams']
                 if stream['codec_type'] == 'video' and not stream.get('disposition', {}).get('attached_pic')),
                None
            )
            
            if not video_info:
                raise ValueError("Видео поток не найден")
            
            audio_info = next(
                (stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), 
                None
            )
            
            fps = video_info.get('r_frame_rate', '30/1')
            rotation = next(
                (entry['rotation'] for entry in video_info.get('side_data_list', []) if 'rotation' in entry),
                0,
            )
            self.video_info = {
                'duration': float(probe['format'].get('duration', 0)),
                'width': video_info.get('width', 0),
                'height': video_info.get('height', 0),
                'fps': float(Fraction(fps)) if fps not in ('0/0', 'N/A') else 0.0,
                'codec': video_info.get('codec_name', 'unknown'),
                'bitrate': video_info.get('bit_rate', 'unknown'),
                'has_audio': audio_info is not None,
                'video_index': video_info['index'],
                'audio_index': audio_info['index'] if audio_info else None,
                'video_duration': video_info.get('duration'),
                'rotation': rotation,
                'sample_aspect_ratio': video_info.get('sample_aspect_ratio'),
                'file_size': os.path.getsize(video_path) / (1024 * 1024),  # MB
            }
            
            self.current_video = video_path
            return self.video_info
            
        except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as error:
            raise ValueError(f"Ошибка при загрузке информации о видео: {error}") from error
    
    def get_frame(self, video_path: str, timestamp: float):
        """Получает кадр видео в указанный момент времени"""
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_number = int(timestamp * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None
            
        except Exception as e:
            print(f"Ошибка при получении кадра: {str(e)}")
            return None
    
    def trim_video(self, input_path: str, output_path: str, 
                   start_time: float, end_time: float, 
                   progress_callback=None) -> bool:
        """
        Обрезает видео без перекодирования (stream copy) - сохраняет качество
        
        Args:
            input_path: путь к исходному видео
            output_path: путь к выходному видео
            start_time: время начала в секундах
            end_time: время окончания в секундах
            progress_callback: callback функция для отслеживания прогресса
        """
        try:
            # Используем stream copy для максимального качества
            stream = (
                ffmpeg
                .input(input_path, ss=start_time, to=end_time)
                .output(output_path, c='copy')
                .overwrite_output()
            )
            process = run_media(ffmpeg.compile(stream), capture_output=True)
            if process.returncode:
                raise ffmpeg.Error("ffmpeg", process.stdout, process.stderr)
            
            return True
            
        except ffmpeg.Error as e:
            error_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            raise Exception(f"Ошибка при обрезке видео: {error_msg}")
        except Exception as e:
            raise Exception(f"Неожиданная ошибка: {str(e)}")
    
    def get_duration(self) -> float:
        """Возвращает длительность текущего видео в секундах"""
        return self.video_info.get('duration', 0)
    
    def format_time(self, seconds: float) -> str:
        """Форматирует время в формат HH:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 100)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:02d}"
    
    def parse_time(self, time_str: str) -> float:
        """Парсит строку времени (HH:MM:SS.MS) в секунды"""
        try:
            parts = time_str.split(':')
            hours = int(parts[0]) if len(parts) > 0 else 0
            minutes = int(parts[1]) if len(parts) > 1 else 0
            
            seconds_part = parts[2] if len(parts) > 2 else '0'
            seconds = float(seconds_part)
            
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
            
        except Exception:
            return 0.0
