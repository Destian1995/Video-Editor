"""Монтаж выбранных диапазонов и экспорт в MP4."""

from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from subprocess import PIPE
from tempfile import TemporaryDirectory

from PyQt5.QtCore import QThread, pyqtSignal

from media_process import open_media


@dataclass(frozen=True)
class CompressionProfile:
    name: str
    crf: int
    audio_kbps: int
    max_video_kbps: int = 0


EXPORT_PROFILES = (
    CompressionProfile("Сбалансированное", 23, 160, 8000),
    CompressionProfile("Компактное", 26, 128, 5000),
    CompressionProfile("Высокое качество", 20, 192),
)


@dataclass(frozen=True)
class Clip:
    path: Path
    start: int
    end: int

    @property
    def duration(self):
        return self.end - self.start


def insert_clip(timeline, clip, position):
    """Вставляет клип в позицию в миллисекундах и возвращает его индекс."""
    if not 0 <= position <= sum(part.duration for part in timeline):
        raise ValueError("Позиция должна находиться в пределах монтажа.")
    for index, part in enumerate(timeline):
        if position == 0:
            timeline.insert(index, clip)
            return index
        if position < part.duration:
            cut = part.start + position
            timeline[index:index + 1] = [replace(part, end=cut), clip, replace(part, start=cut)]
            return index + 1
        position -= part.duration
    timeline.append(clip)
    return len(timeline) - 1


def montage_fps(timeline, sources):
    return min(60, max(1, round(sources[timeline[0].path]["fps"] or 30)))


def clip_frames(clip, fps):
    return max(1, round(clip.duration * fps / 1000))


def montage_command(timeline, sources, output, profile=EXPORT_PROFILES[2]):
    first = sources[timeline[0].path]
    width, height = first["width"], first["height"]
    sar = first["sample_aspect_ratio"]
    if sar and sar not in ("N/A", "0:1"):
        width = round(width * Fraction(sar.replace(":", "/")))
    if first["rotation"] % 180:
        width, height = height, width
    width, height = max(2, width // 2 * 2), max(2, height // 2 * 2)
    fps = montage_fps(timeline, sources)
    with_audio = any(sources[part.path]["has_audio"] for part in timeline)
    args = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-xerror", "-abort_on", "empty_output_stream", "-n",
        "-nostats", "-stats_period", "0.5", "-progress", "pipe:1",
    ]
    graph, inputs = [], []
    for index, part in enumerate(timeline):
        info = sources[part.path]
        seconds = part.duration / 1000
        frames = clip_frames(part, fps)
        source_frame = 1 / (info["fps"] or fps)
        start = part.start / 1000
        video_end = info.get("duration_ms")
        if video_end is not None:
            start = min(start, max(0, video_end / 1000 - source_frame))
        read_duration = seconds + 2 * source_frame
        args += [
            "-threads", "2", "-ss", f"{start:.6f}",
            "-t", f"{read_duration:.6f}", "-i", str(part.path),
        ]
        video = f"[v{index}]"
        graph.append(
            f"[{index}:{info['video_index']}]setpts=PTS-STARTPTS,"
            "scale=w='max(2,trunc(iw*sar/2)*2)':h='max(2,trunc(ih/2)*2)',setsar=1,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,"
            f"fps={fps}:eof_action=pass,tpad=stop_mode=clone:stop=-1,"
            f"trim=end_frame={frames}{video}"
        )
        inputs.append(video)
        audio = f"[a{index}]"
        stream = info["audio_index"]
        source = (
            "anullsrc=r=48000:cl=stereo"
            if stream is None else
            f"[{index}:{stream}]aresample=48000:async=1:first_pts=0,"
            "aformat=channel_layouts=stereo,apad"
        )
        # A silent segment still needs a duration when it contains just one frame.
        graph.append(f"{source},atrim=end_sample={round(frames * 48000 / fps)},asetpts=PTS-STARTPTS{audio}")
        inputs.append(audio)

    graph.append(f"{''.join(inputs)}concat=n={len(timeline)}:v=1:a=1[video][audio]")
    if not with_audio:
        graph.append("[audio]anullsink")
    args += [
        "-filter_complex_threads", "4", "-filter_complex", ";".join(graph),
        "-map", "[video]", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", str(profile.crf), "-fps_mode", "vfr",
    ]
    if profile.max_video_kbps:
        args += ["-maxrate", f"{profile.max_video_kbps}k", "-bufsize", f"{2 * profile.max_video_kbps}k"]
    if with_audio:
        args += ["-map", "[audio]", "-c:a", "aac", "-b:a", f"{profile.audio_kbps}k"]
    return args + ["-movflags", "+faststart", str(output)]


class MontageExport(QThread):
    progress = pyqtSignal(int, float)
    finalizing = pyqtSignal()

    def __init__(self, timeline, sources, output, parent, profile=EXPORT_PROFILES[2]):
        super().__init__(parent)
        self.timeline = timeline
        self.sources = sources
        self.output = output
        self.profile = profile
        fps = montage_fps(timeline, sources)
        self.duration_ms = round(sum(clip_frames(part, fps) for part in timeline) * 1000 / fps)
        self.error = ""
        self.size = 0

    def run(self):
        try:
            with TemporaryDirectory(prefix=".video-editor-", dir=self.output.parent) as directory:
                temporary = Path(directory) / "export.mp4"
                command = montage_command(self.timeline, self.sources, temporary, self.profile)
                with temporary.with_suffix(".log").open("w+b") as errors:
                    with open_media(command, stdout=PIPE, stderr=errors) as process:
                        self.read_progress(process.stdout)
                        if process.wait():
                            errors.seek(0)
                            self.error = errors.read().decode("utf-8", errors="replace").strip() or "Ошибка FFmpeg."
                            return
                self.finalizing.emit()
                self.size = temporary.stat().st_size
                temporary.replace(self.output)
        except (OSError, ValueError, ZeroDivisionError) as error:
            self.error = str(error)

    def read_progress(self, stream):
        values = {}
        for line in stream:
            key, _, value = line.strip().partition(b"=")
            if key != b"progress":
                values[key] = value
                continue
            timestamp = values.get(b"out_time_us", b"")
            speed = values.get(b"speed", b"").rstrip(b"x")
            if timestamp.lstrip(b"-").isdigit():
                try:
                    rate = float(speed)
                except ValueError:
                    rate = 0.0
                self.progress.emit(max(0, int(timestamp) // 1000), rate)
            values.clear()
