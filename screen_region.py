"""Выбор области рабочего стола и перевод координат Qt в пиксели Windows."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from PyQt5.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen, QRegion
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


def default_capture_region(window_id):
    monitor = _window_monitor_bounds(window_id)
    width, height = monitor.width() // 4 * 2, monitor.height() // 4 * 2
    if width < 2 or height < 2:
        return None
    return CaptureRegion(
        monitor.x() + (monitor.width() - width) // 2,
        monitor.y() + (monitor.height() - height) // 2,
        width, height,
    )


def _region_monitor_bounds(region):
    user32 = ctypes.WinDLL("user32")
    from_rect = user32.MonitorFromRect
    from_rect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    from_rect.restype = wintypes.HANDLE
    rect = wintypes.RECT(region.x, region.y, region.x + region.width, region.y + region.height)
    return _monitor_bounds(user32, from_rect(ctypes.byref(rect), 0))


def region_is_available(region):
    return region is not None and _region_monitor_bounds(region).contains(
        QRect(region.x, region.y, region.width, region.height)
    )


def exclude_from_capture(window_id):
    exclude = ctypes.WinDLL("user32").SetWindowDisplayAffinity
    exclude.argtypes = [wintypes.HWND, wintypes.DWORD]
    exclude.restype = wintypes.BOOL
    return bool(exclude(window_id, 0x11))


def _physical_cursor():
    get_cursor = ctypes.WinDLL("user32").GetPhysicalCursorPos
    get_cursor.argtypes = [ctypes.POINTER(wintypes.POINT)]
    get_cursor.restype = wintypes.BOOL
    point = wintypes.POINT()
    if get_cursor(ctypes.byref(point)):
        return QPoint(point.x, point.y)
    return QCursor.pos()


def resize_region(region, edges, delta, monitor):
    left, top = region.x, region.y
    right, bottom = left + region.width, top + region.height
    if edges & Qt.LeftEdge:
        left = min(right - 2, max(monitor.left(), left + delta.x()))
        left += (right - left) % 2
    elif edges & Qt.RightEdge:
        right = max(left + 2, min(monitor.right() + 1, right + delta.x()))
        right -= (right - left) % 2
    if edges & Qt.TopEdge:
        top = min(bottom - 2, max(monitor.top(), top + delta.y()))
        top += (bottom - top) % 2
    elif edges & Qt.BottomEdge:
        bottom = max(top + 2, min(monitor.bottom() + 1, bottom + delta.y()))
        bottom -= (bottom - top) % 2
    return CaptureRegion(left, top, right - left, bottom - top)


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


class RegionOutline(QWidget):
    resized_region = pyqtSignal(object)
    thickness = 6

    def __init__(self, region):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.area = region
        self.drag = None
        self.monitor = _region_monitor_bounds(region)
        screen = next(
            (screen for screen in QApplication.screens() if screen.geometry().topLeft() == self.monitor.topLeft()),
            QApplication.primaryScreen(),
        )
        self.screen_bounds = screen.geometry()
        self.winId()
        self.windowHandle().setScreen(screen)
        self.set_region(region)
        exclude_from_capture(int(self.winId()))

    def contains_region(self, region):
        return self.monitor.contains(QRect(region.x, region.y, region.width, region.height))

    def set_region(self, region):
        self.area = region
        physical, logical = self.monitor, self.screen_bounds
        if physical.isEmpty():
            return
        sx, sy = logical.width() / physical.width(), logical.height() / physical.height()
        x, y = region.x - physical.x(), region.y - physical.y()
        left, top = round(x * sx), round(y * sy)
        right, bottom = round((x + region.width) * sx), round((y + region.height) * sy)
        inner = QRect(logical.x() + left, logical.y() + top, max(1, right - left), max(1, bottom - top))
        border = self.thickness
        outer = inner.adjusted(-border, -border, border, border).intersected(logical)
        hole = inner.adjusted(
            max(0, border - (inner.left() - outer.left())),
            max(0, border - (inner.top() - outer.top())),
            -max(0, border - (outer.right() - inner.right())),
            -max(0, border - (outer.bottom() - inner.bottom())),
        )
        self.setGeometry(outer)
        self.setMask(QRegion(self.rect()).subtracted(QRegion(hole.translated(-outer.topLeft()))))

    def _edges(self, point):
        x, y = point.x(), point.y()
        left, top = x < self.width() / 2, y < self.height() / 2
        dx = x if left else self.width() - 1 - x
        dy = y if top else self.height() - 1 - y
        horizontal = Qt.LeftEdge if left else Qt.RightEdge
        vertical = Qt.TopEdge if top else Qt.BottomEdge
        if dx < 14 and dy < 14:
            cursor = Qt.SizeBDiagCursor if left == top else Qt.SizeFDiagCursor
            return horizontal | vertical, cursor
        return (horizontal, Qt.SizeHorCursor) if dx < dy else (vertical, Qt.SizeVerCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edges, cursor = self._edges(event.pos())
            self.setCursor(cursor)
            self.drag = self.area, edges, _physical_cursor()

    def _update_drag(self):
        original, edges, anchor = self.drag
        self.set_region(resize_region(original, edges, _physical_cursor() - anchor, self.monitor))

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self._update_drag()
        else:
            self.setCursor(self._edges(event.pos())[1])

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drag is not None:
            original = self.drag[0]
            self._update_drag()
            self.drag = None
            if self.area != original:
                self.resized_region.emit(self.area)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#bb9dff"))


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
