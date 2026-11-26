"""Запуск утилит FFmpeg и поиск сборки, установленной через WinGet."""

import os
from pathlib import Path
from shutil import which
import subprocess
import sys


def configure_ffmpeg_path():
    if sys.platform != "win32" or (which("ffmpeg") and which("ffprobe")):
        return
    local_data = os.environ.get("LOCALAPPDATA")
    if not local_data:
        return
    winget = Path(local_data) / "Microsoft" / "WinGet"
    candidates = [winget / "Links"]
    candidates.extend(sorted(
        (winget / "Packages").glob("Gyan.FFmpeg_*/ffmpeg-*/bin"),
        reverse=True,
    ))
    for directory in candidates:
        if all((directory / executable).is_file() for executable in ("ffmpeg.exe", "ffprobe.exe")):
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            break


def run_media(command, **options):
    return subprocess.run(
        command, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **options,
    )


def open_media(command, **options):
    return subprocess.Popen(
        command, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **options,
    )
