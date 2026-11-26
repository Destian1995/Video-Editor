"""Асинхронная сборка записанных между паузами фрагментов."""

import json

from PyQt5.QtCore import QThread

from media_process import run_media


class JoinSegments(QThread):
    def __init__(self, segments, output, parent):
        super().__init__(parent)
        self.segments = segments
        self.output = output
        self.error = ""

    def run(self):
        try:
            args = self._command()
            result = run_media(args, capture_output=True)
            if result.returncode:
                self.error = result.stderr.decode("utf-8", errors="replace").strip() or "Ошибка FFmpeg"
        except (OSError, ValueError, KeyError, IndexError) as error:
            self.error = str(error)

    def _command(self):
        args = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-n"]
        video_info = []
        for path, _ in self.segments:
            args += ["-i", str(path)]
            probe = run_media([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=width,height,duration:format=duration", "-of", "json", str(path),
            ], capture_output=True)
            if probe.returncode:
                raise ValueError(probe.stderr.decode("utf-8", errors="replace").strip())
            info = json.loads(probe.stdout)
            stream = info["streams"][0]
            duration = stream.get("duration") or info["format"]["duration"]
            video_info.append((int(stream["width"]), int(stream["height"]), float(duration)))

        width, height, _ = video_info[0]
        with_audio = any(audio for _, audio in self.segments)
        filters = []
        inputs = []
        for index, ((_, audio), (_, _, duration)) in enumerate(zip(self.segments, video_info)):
            video = f"[v{index}]"
            filters.append(
                f"[{index}:v:0]settb=AVTB,setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p{video}"
            )
            inputs.append(video)
            if with_audio:
                channel = f"[a{index}]"
                if audio:
                    source = f"[{index}:a:0]aresample=48000,aformat=channel_layouts=stereo,apad"
                else:
                    source = "anullsrc=r=48000:cl=stereo"
                filters.append(f"{source},atrim=duration={duration:.6f},asetpts=PTS-STARTPTS{channel}")
                inputs.append(channel)

        outputs = "[video][audio]" if with_audio else "[video]"
        filters.append(f"{''.join(inputs)}concat=n={len(self.segments)}:v=1:a={int(with_audio)}{outputs}")
        args += [
            "-filter_complex", ";".join(filters), "-map", "[video]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-fps_mode", "vfr",
            "-pix_fmt", "yuv420p",
        ]
        if with_audio:
            args += ["-map", "[audio]", "-c:a", "aac", "-b:a", "192k"]
        return args + ["-movflags", "+faststart", str(self.output)]
