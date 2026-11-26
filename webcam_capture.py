"""Обнаружение камер DirectShow и позиции вставки в записываемом кадре."""

import re

from media_process import run_media


WEBCAM_POSITIONS = {
    "top_left": ("Сверху слева", "{margin}", "{margin}"),
    "top_center": ("Сверху по центру", "(W-w)/2", "{margin}"),
    "top_right": ("Сверху справа", "W-w-{margin}", "{margin}"),
    "middle_left": ("Слева по центру", "{margin}", "(H-h)/2"),
    "middle_right": ("Справа по центру", "W-w-{margin}", "(H-h)/2"),
    "bottom_left": ("Снизу слева", "{margin}", "H-h-{margin}"),
    "bottom_center": ("Снизу по центру", "(W-w)/2", "H-h-{margin}"),
    "bottom_right": ("Снизу справа", "W-w-{margin}", "H-h-{margin}"),
}
DEFAULT_WEBCAM_POSITION = "bottom_right"
DEFAULT_WEBCAM_BORDER_STYLE = "thin"
DEFAULT_WEBCAM_BORDER_COLOR = "#bb9dff"
WEBCAM_BORDER_STYLES = {
    "thin": ("Тонкая", ((4, None),)),
    "wide": ("Широкая", ((8, None),)),
    "double": ("Двойная", ((2, None), (2, "#1b1629"), (2, None))),
    "none": ("Без рамки", ()),
}


def webcam_position(position):
    return WEBCAM_POSITIONS.get(position, WEBCAM_POSITIONS[DEFAULT_WEBCAM_POSITION])


def webcam_border_style(style):
    return style if style in WEBCAM_BORDER_STYLES else DEFAULT_WEBCAM_BORDER_STYLE


def webcam_border_color(color):
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color.lower()
    return DEFAULT_WEBCAM_BORDER_COLOR


def webcam_border_layers(style, color):
    _, layers = WEBCAM_BORDER_STYLES[webcam_border_style(style)]
    accent = webcam_border_color(color)
    return [(width, fixed_color or accent) for width, fixed_color in layers]


def webcam_frame_filter(width, height, border_style, border_color):
    border = "".join(
        f",pad=iw+{2 * edge}:ih+{2 * edge}:{edge}:{edge}:color=0x{color[1:]}"
        for edge, color in webcam_border_layers(border_style, border_color)
    )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2,setsar=1{border}"
    )


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


def webcam_overlay(
    graph, position, border_style=DEFAULT_WEBCAM_BORDER_STYLE,
    border_color=DEFAULT_WEBCAM_BORDER_COLOR, input_index=0, region=None,
):
    _, x, y = webcam_position(position)
    width, height, margin = 320, 180, 18
    if region is not None:
        width = min(width, max(2, region.width // 6 * 2))
        height = min(height, max(2, region.height // 6 * 2))
        margin = min(margin, min(region.width, region.height) // 8)
    x = x.format(margin=margin)
    y = y.format(margin=margin)
    frame = webcam_frame_filter(width, height, border_style, border_color)
    return (
        f"{graph}[desktop];"
        f"[{input_index}:v]setpts=PTS-STARTPTS,{frame}[camera];"
        f"[desktop]setpts=PTS-STARTPTS[desktop_start];"
        f"[desktop_start][camera]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0"
    )
