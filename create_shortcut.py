"""Создаёт ярлык Video Editor для текущей папки проекта на Windows."""

import os
from pathlib import Path
from shutil import which
import subprocess
import sys


CREATE_SHORTCUT = """
$ErrorActionPreference = 'Stop'
$project = (Get-Location).Path
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $project 'Video Editor.lnk'))
$shortcut.TargetPath = $env:VIDEO_EDITOR_SHORTCUT_PYTHONW
$shortcut.Arguments = [char]34 + (Join-Path $project 'main.py') + [char]34
$shortcut.WorkingDirectory = $project
$shortcut.IconLocation = (Join-Path $project 'video-editor.ico') + ',0'
$shortcut.Description = 'Video Editor - screen recorder and video editor'
$shortcut.Save()
"""


def main():
    if sys.platform != "win32":
        raise SystemExit("Ярлык .lnk поддерживается только на Windows.")

    project = Path(__file__).resolve().parent
    local_pythonw = project / ".venv" / "Scripts" / "pythonw.exe"
    current_pythonw = Path(sys.executable).with_name("pythonw.exe")
    pythonw = next(
        (str(candidate) for candidate in (local_pythonw, current_pythonw) if candidate.is_file()),
        which("pythonw.exe"),
    )
    if not pythonw:
        raise SystemExit("Не найден pythonw.exe. Установите Python или создайте окружение .venv.")

    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", CREATE_SHORTCUT],
        cwd=project,
        env={**os.environ, "VIDEO_EDITOR_SHORTCUT_PYTHONW": pythonw},
        check=True,
    )
    print(project / "Video Editor.lnk")


if __name__ == "__main__":
    main()
