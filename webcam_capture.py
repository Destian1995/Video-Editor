"""Обнаружение камер DirectShow и позиции вставки в записываемом кадре."""

import re

from media_process import run_media


WEBCAM_POSITIONS = {
    "top_left": ("Сверху слева", "18", "18"),
    "top_center": ("Сверху по центру", "(W-w)/2", "18"),
    "top_right": ("Сверху справа", "W-w-18", "18"),
    "middle_left": ("Слева по центру", "18", "(H-h)/2"),
    "middle_right": ("Справа по центру", "W-w-18", "(H-h)/2"),
    "bottom_left": ("Снизу слева", "18", "H-h-18"),
    "bottom_center": ("Снизу по центру", "(W-w)/2", "H-h-18"),
    "bottom_right": ("Снизу справа", "W-w-18", "H-h-18"),
}
DEFAULT_WEBCAM_POSITION = "bottom_right"


def webcam_position(position):
    return WEBCAM_POSITIONS.get(position, WEBCAM_POSITIONS[DEFAULT_WEBCAM_POSITION])


def webcam_devices():
    result = run_media(
        ["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True, timeout=5,
    )
    devices = {}
    video_name = None
    for line in result.stderr.decode("utf-8", errors="replace").splitlines():
        alternate = re.search(r'Alternative name "(.+)"', line)
        if video_name is not None and alternate:
            devices[alternate.group(1)] = video_name
            video_name = None
            continue
        camera = re.search(r'"(.+)" \(video\)', line)
        video_name = camera.group(1) if camera else None
    return devices


def webcam_overlay(graph, position):
    _, x, y = webcam_position(position)
    return (
        f"{graph}[desktop];"
        "[0:v]setpts=PTS-STARTPTS,scale=320:180:force_original_aspect_ratio=decrease:"
        "force_divisible_by=2,setsar=1,pad=iw+8:ih+8:4:4:color=0xbb9dff[camera];"
        f"[desktop]setpts=PTS-STARTPTS[desktop_start];"
        f"[desktop_start][camera]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0"
    )
