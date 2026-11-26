"""Выбор области рабочего стола и перевод координат Qt в пиксели Windows."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from PyQt5.QtCore import QObject, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget


RECORDING_MODES = {"game": "Игровой", "region": "Обычный"}


@dataclass(frozen=True)
class CaptureRegion:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        if self.width < 2 or self.height < 2:
            raise ValueError("Область записи должна содержать не менее двух пикселей по каждой стороне.")

    @property
    def size(self):
        return f"{self.width}x{self.height}"

    def serialize(self):
        return f"{self.x},{self.y},{self.width},{self.height}"

    @classmethod
    def parse(cls, value):
        try:
            return cls(*map(int, value.split(","))) if value else None
        except (TypeError, ValueError):
            return None

    def ffmpeg_args(self, fps):
        return [
            "-thread_queue_size", "16", "-f", "gdigrab", "-framerate", str(fps),
            "-offset_x", str(self.x), "-offset_y", str(self.y),
            "-video_size", self.size, "-draw_mouse", "0", "-i", "desktop",
        ]


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("bounds", wintypes.RECT),
        ("work_area", wintypes.RECT), ("flags", wintypes.DWORD),
    ]


def _monitor_bounds(user32, monitor):
    get_info = user32.GetMonitorInfoW
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    get_info.restype = wintypes.BOOL
    info = MonitorInfo(ctypes.sizeof(MonitorInfo))
    if not monitor or not get_info(monitor, ctypes.byref(info)):
        return QRect()
    rect = info.bounds
    return QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def _window_monitor_bounds(window_id):
    user32 = ctypes.WinDLL("user32")
    from_window = user32.MonitorFromWindow
    from_window.argtypes = [wintypes.HWND, wintypes.DWORD]
    from_window.restype = wintypes.HANDLE
    return _monitor_bounds(user32, from_window(window_id, 2))


def region_is_available(region):
    if region is None:
        return False
    user32 = ctypes.WinDLL("user32")
    from_rect = user32.MonitorFromRect
    from_rect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    from_rect.restype = wintypes.HANDLE
    rect = wintypes.RECT(region.x, region.y, region.x + region.width, region.y + region.height)
    bounds = _monitor_bounds(user32, from_rect(ctypes.byref(rect), 0))
    return bounds.contains(QRect(region.x, region.y, region.width, region.height))


def pixels_from_selection(selection, canvas, monitor):
    if selection.isEmpty() or canvas.isEmpty() or monitor.isEmpty():
        return None
    scale_x = monitor.width() / canvas.width()
    scale_y = monitor.height() / canvas.height()
    left = round(selection.x() * scale_x)
    top = round(selection.y() * scale_y)
    width = round((selection.x() + selection.width()) * scale_x) - left
    height = round((selection.y() + selection.height()) * scale_y) - top
    try:
        return CaptureRegion(monitor.x() + left, monitor.y() + top, width - width % 2, height - height % 2)
    except ValueError:
        return None


class RegionOverlay(QWidget):
    selected = pyqtSignal(object)

    def __init__(self, screen):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.anchor = None
        self.selection = QRect()
        self.winId()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.anchor = event.pos()
            self.selection = QRect()
            self.update()
        elif event.button() == Qt.RightButton:
            self.selected.emit(None)

    def _update_selection(self, point):
        self.selection = QRect(self.anchor, point).normalized().intersected(self.rect())
        self.update()

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self._update_selection(event.pos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.anchor is not None:
            self._update_selection(event.pos())
            self.anchor = None
            monitor = _window_monitor_bounds(int(self.winId()))
            region = pixels_from_selection(self.selection, self.rect(), monitor)
            if region is not None:
                self.selected.emit(region)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.selected.emit(None)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(14, 10, 22, 155))
        if not self.selection.isEmpty():
            painter.fillRect(self.selection, QColor(0, 0, 0, 0))
            painter.setPen(QPen(QColor("#bb9dff"), 2))
            painter.drawRect(self.selection.adjusted(1, 1, -1, -1))
        else:
            banner = QRect(0, 22, self.width(), 42)
            painter.setPen(QColor("#f4f0ff"))
            painter.drawText(banner, Qt.AlignCenter, "Выделите область мышью   ·   Esc — отмена")


class ScreenRegionSelector(QObject):
    selected = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.overlays = []

    def open(self):
        screens = QApplication.screens()
        active_screen = QApplication.screenAt(QCursor.pos())
        for screen in screens:
            overlay = RegionOverlay(screen)
            overlay.selected.connect(self.finish)
            self.overlays.append(overlay)
            overlay.show()
            if screen == active_screen:
                overlay.activateWindow()
        if not self.overlays:
            self.selected.emit(None)

    def finish(self, region):
        for overlay in self.overlays:
            overlay.hide()
            overlay.deleteLater()
        self.overlays.clear()
        self.selected.emit(region)
