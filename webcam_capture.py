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
DEFAULT_WEBCAM_SIZE = "small"
WEBCAM_SIZES = {
    "small": ("Маленький", 4),
    "medium": ("Средний", 5),
    "large": ("Большой", 6),
    "extra_large": ("Очень большой", 8),
}
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


def webcam_size(size):
    return size if size in WEBCAM_SIZES else DEFAULT_WEBCAM_SIZE


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


def webcam_margin(region):
    return 18 if region is None else min(18, min(region.width, region.height) // 8)


def webcam_frame_size(size, region=None, border_style=DEFAULT_WEBCAM_BORDER_STYLE):
    _, scale = WEBCAM_SIZES[webcam_size(size)]
    width, height = 320, 180
    if region is not None:
        width = min(width, region.width // 6 * 2)
        height = min(height, region.height // 6 * 2)
    width, height = width * scale // 8 * 2, height * scale // 8 * 2
    if region is not None:
        _, layers = WEBCAM_BORDER_STYLES[webcam_border_style(border_style)]
        inset = 2 * (webcam_margin(region) + sum(edge for edge, _ in layers))
        width = min(width, (region.width - inset) // 2 * 2)
        height = min(height, (region.height - inset) // 2 * 2)
    return max(2, width), max(2, height)


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
    border_color=DEFAULT_WEBCAM_BORDER_COLOR, input_index=0, region=None, size=DEFAULT_WEBCAM_SIZE,
):
    _, x, y = webcam_position(position)
    width, height = webcam_frame_size(size, region, border_style)
    margin = webcam_margin(region)
    x = x.format(margin=margin)
    y = y.format(margin=margin)
    frame = webcam_frame_filter(width, height, border_style, border_color)
    return (
        f"{graph}[desktop];"
        f"[{input_index}:v]setpts=PTS-STARTPTS,{frame}[camera];"
        f"[desktop]setpts=PTS-STARTPTS[desktop_start];"
        f"[desktop_start][camera]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0"
    )
