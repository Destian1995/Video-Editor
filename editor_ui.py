"""Оформление и виджеты интерфейса Video Editor."""

import ctypes
from ctypes import wintypes
from math import ceil
import sys

from PyQt5.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PyQt5.QtGui import (
    QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient, QTextOption,
)
from PyQt5.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QLabel, QSizePolicy, QTabBar,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)


def style_title_bar(window):
    if sys.platform != "win32" or sys.getwindowsversion().build < 22000:
        return
    set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
    set_attribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD,
    ]
    set_attribute.restype = ctypes.c_long
    dwmwa_caption_color = 35
    dwmwa_text_color = 36
    for attribute, color in ((dwmwa_caption_color, QColor("#12121b")), (dwmwa_text_color, QColor("#f4f0ff"))):
        colorref = wintypes.DWORD(color.red() | (color.green() << 8) | (color.blue() << 16))
        set_attribute(int(window.winId()), attribute, ctypes.byref(colorref), ctypes.sizeof(colorref))


def label(text, role):
    widget = QLabel(text)
    widget.setObjectName(role)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(13)
    return widget, layout


def recording_mode_icon(mode):
    pixmap = QPixmap(40, 40)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor("#e4d3ff")
    painter.setPen(QPen(color, 1.45, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if mode == "game":
        controller = QPainterPath(QPointF(6, 5))
        controller.lineTo(14, 5)
        controller.cubicTo(17, 5, 18.2, 7.2, 19, 13.2)
        controller.cubicTo(19.3, 16.3, 17.4, 17.1, 15.5, 15.4)
        controller.lineTo(13, 13.2)
        controller.lineTo(7, 13.2)
        controller.lineTo(4.5, 15.4)
        controller.cubicTo(2.6, 17.1, .7, 16.3, 1, 13.2)
        controller.cubicTo(1.8, 7.2, 3, 5, 6, 5)
        painter.drawPath(controller)
        painter.drawLine(QPointF(4.4, 9.2), QPointF(8.3, 9.2))
        painter.drawLine(QPointF(6.35, 7.25), QPointF(6.35, 11.15))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(12.8, 10), .9, .9)
        painter.drawEllipse(QPointF(15, 8), .9, .9)
    else:
        painter.drawRoundedRect(QRectF(1.8, 5.5, 11.5, 9), 2, 2)
        painter.drawPolyline(QPolygonF([QPointF(13.3, 8.7), QPointF(18.2, 6.2),
                                       QPointF(18.2, 13.8), QPointF(13.3, 11.3)]))
    painter.end()
    return QIcon(pixmap)


class AnimatedTabBar(QTabBar):
    def __init__(self):
        super().__init__()
        self.setDrawBase(False)
        self.setExpanding(False)
        self.underline = QRectF()
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(190)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._set_underline)
        self.currentChanged.connect(self._move_underline)

    def _target_underline(self, index):
        tab = QRectF(self.tabRect(index))
        return QRectF(tab.left() + 6, tab.bottom() - 2, max(0, tab.width() - 12), 2)

    def _set_underline(self, bounds):
        self.underline = bounds
        self.update()

    def _move_underline(self, index):
        self.animation.stop()
        target = self._target_underline(index)
        if self.isVisible() and not self.underline.isEmpty():
            self.animation.setStartValue(self.underline)
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._set_underline(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.animation.stop()
        self._set_underline(self._target_underline(self.currentIndex()))

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ba9aff"))
        painter.drawRoundedRect(self.underline, 1, 1)


class EditorTabs(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setTabBar(AnimatedTabBar())
        self.setDocumentMode(True)
        self.tabBar().setDrawBase(False)
        self.fading_page = None
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(165)
        self.fade.setStartValue(0.45)
        self.fade.setEndValue(1.0)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.valueChanged.connect(self._set_page_opacity)
        self.fade.finished.connect(self._clear_fade)
        self.currentChanged.connect(self._fade_in_page)

    def _fade_in_page(self, index):
        self.fade.stop()
        self._clear_fade()
        if not self.isVisible() or index < 0:
            return
        self.fading_page = self.widget(index)
        effect = QGraphicsOpacityEffect(self.fading_page)
        effect.setOpacity(self.fade.startValue())
        self.fading_page.setGraphicsEffect(effect)
        self.fade.start()

    def _set_page_opacity(self, opacity):
        if self.fading_page is not None:
            self.fading_page.graphicsEffect().setOpacity(opacity)

    def _clear_fade(self):
        if self.fading_page is not None:
            self.fading_page.setGraphicsEffect(None)
            self.fading_page = None


class FileLabel(QLabel):
    def __init__(self, role="muted"):
        super().__init__()
        self.setObjectName(role)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextFormat(Qt.PlainText)
        self.filename = ""

    def set_file(self, path):
        self.set_full_text(path.name, str(path))
        self.show()

    def set_full_text(self, text, tooltip=None):
        self.filename = text
        self.setToolTip(text if tooltip is None else tooltip)
        self._fit_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def _fit_text(self):
        text = self.fontMetrics().elidedText(self.filename, Qt.ElideMiddle, self.contentsRect().width())
        self.setText(text)


class RecordingStatus(QTextEdit):
    def __init__(self, message):
        super().__init__()
        self.setObjectName("recordingStatus")
        self.setAccessibleName("Статус записи")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)
        self.set_message(message)

    def set_message(self, message):
        self.setPlainText(message)
        self.setToolTip(message)

    def _fit_height(self, size):
        self.setFixedHeight(ceil(size.height()))


class WebcamBorderPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setAccessibleName("Предпросмотр рамки веб-камеры")
        self.setFixedSize(148, 100)
        self.layers = []

    def set_layers(self, layers):
        self.layers = layers
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#514467"), 1))
        painter.setBrush(QColor("#14121e"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)

        image = QRectF(20, 20, 108, 60)
        border = sum(width for width, _ in self.layers)
        bounds = image.adjusted(-border, -border, border, border)
        for width, color in reversed(self.layers):
            painter.fillRect(bounds, QColor(color))
            bounds.adjust(width, width, -width, -width)
        gradient = QLinearGradient(image.topLeft(), image.bottomRight())
        gradient.setColorAt(0, QColor("#403452"))
        gradient.setColorAt(1, QColor("#252238"))
        painter.fillRect(image, gradient)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#8875a6"))
        painter.drawEllipse(QPointF(74, 44), 9, 9)
        painter.drawRoundedRect(QRectF(57, 55, 34, 17), 8, 8)


class FramePreview(QLabel):
    empty_text = "Откройте видео для предпросмотра"

    def __init__(self):
        super().__init__(self.empty_text)
        self.setObjectName("framePreview")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(240, 160)
        self.frame = QPixmap()

    def clear_frame(self):
        self.frame = QPixmap()
        self.setText(self.empty_text)

    def set_frame(self, image):
        self.frame = QPixmap.fromImage(image)
        self._fit_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_frame()

    def _fit_frame(self):
        if not self.frame.isNull():
            self.setPixmap(self.frame.scaled(
                self.contentsRect().size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.frame.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.translate(QPointF(self.width() / 2, self.height() / 2 - 39))
            painter.setPen(QPen(QColor("#59466f"), 1.5))
            painter.setBrush(QColor("#252033"))
            painter.drawEllipse(QPointF(), 16, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#c2a8fa"))
            painter.drawPolygon(QPolygonF([QPointF(-4, -6), QPointF(6, 0), QPointF(-4, 6)]))


class CaptureIllustration(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.recording = False
        self.pulse = QVariantAnimation(self)
        self.pulse.setStartValue(0.0)
        self.pulse.setEndValue(1.0)
        self.pulse.setDuration(1550)
        self.pulse.setLoopCount(-1)
        self.pulse.valueChanged.connect(self.update)

    def set_recording(self, recording):
        if self.recording != recording:
            self.recording = recording
            self._refresh_pulse()
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_pulse()

    def hideEvent(self, event):
        self.pulse.stop()
        super().hideEvent(event)

    def _refresh_pulse(self):
        if self.recording and self.isVisible():
            self.pulse.start()
        else:
            self.pulse.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        glow = QRadialGradient(bounds.center(), max(bounds.width(), bounds.height()) * 0.55)
        glow.setColorAt(0, QColor("#2f2450"))
        glow.setColorAt(0.52, QColor("#1b1831"))
        glow.setColorAt(1, QColor("#101019"))
        painter.setPen(QPen(QColor("#38304e"), 1))
        painter.setBrush(glow)
        painter.drawRoundedRect(bounds, 14, 14)

        painter.setPen(QPen(QColor(181, 153, 253, 44), 1))
        for x in range(23, self.width() - 18, 22):
            for y in range(23, self.height() - 18, 22):
                painter.drawPoint(x, y)

        scale = min(bounds.width() / 535, bounds.height() / 330)
        painter.translate(bounds.center())
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#7459b5"), 2))
        painter.setBrush(QColor("#1b1730"))
        painter.drawRoundedRect(QRectF(-157, -100, 314, 184), 17, 17)
        screen = QLinearGradient(-132, -86, 125, 65)
        screen.setColorAt(0, QColor("#312553"))
        screen.setColorAt(1, QColor("#171426"))
        painter.setBrush(screen)
        painter.setPen(QPen(QColor("#514274"), 1))
        painter.drawRoundedRect(QRectF(-143, -86, 286, 151), 10, 10)

        accent = QColor("#ff7294" if self.recording else "#ba9aff")
        painter.setPen(QPen(accent, 2.5, Qt.SolidLine, Qt.RoundCap))
        for x, dx in ((-116, 17), (116, -17)):
            for y, dy in ((-59, 17), (38, -17)):
                painter.drawLine(x, y, x + dx, y)
                painter.drawLine(x, y, x, y + dy)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, -10), 27, 27)
        if self.recording:
            phase = self.pulse.currentValue()
            wave = QColor(accent)
            wave.setAlpha(int(135 * (1 - phase)))
            painter.setPen(QPen(wave, 2))
            radius = 27 + 20 * phase
            painter.drawEllipse(QPointF(0, -10), radius, radius)
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QPointF(0, -10), 11, 11)

        painter.setPen(QPen(QColor("#7459b5"), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(0, 84, 0, 110)
        painter.drawLine(-43, 110, 43, 110)


EDITOR_STYLE = """
QMainWindow, QWidget#workspace, QDialog, QMessageBox {
    background: #12121b;
    color: #f4f0ff;
}
QWidget {
    color: #f4f0ff;
    font-family: "Segoe UI";
    font-size: 14px;
}
QLabel { background: transparent; }
QLabel#brand { font-size: 23px; font-weight: 700; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
QLabel#muted { color: #b3acc7; }
QLabel#value { color: #f4f0ff; font-weight: 600; }
QTextEdit#recordingStatus {
    color: #f4f0ff;
    background: transparent;
    border: 0;
    font-weight: 600;
    selection-background-color: #5a417f;
}
QLabel#timecode { color: #d6c9f6; font-family: Consolas; }
QLabel#keycap {
    color: #e8dcff;
    background: #262039;
    border: 1px solid #493a62;
    border-radius: 6px;
    padding: 3px 8px;
    font-family: Consolas;
    font-weight: 700;
}
QLabel#captureState {
    background: #29213b;
    border: 1px solid #46345d;
    border-radius: 9px;
    color: #d9c4ff;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 700;
}
QLabel#captureState[recording="true"] {
    background: #462439;
    border-color: #743952;
    color: #ffadc1;
}
QTabWidget::pane { border: 0; border-top: 1px solid #2a2638; }
QTabBar { font-weight: 600; }
QTabBar::tab {
    color: #b3acc7;
    background: transparent;
    border-bottom: 2px solid transparent;
    padding: 10px 18px;
    min-width: 108px;
    margin-right: 5px;
}
QTabBar::tab:hover { color: #f4f0ff; background: #1f1c2c; }
QTabBar::tab:selected { color: #ddcaff; }
QFrame#card {
    background: #1b1927;
    border: 1px solid #332d43;
    border-radius: 15px;
}
QLabel#framePreview {
    color: #a39bb8;
    background: #101019;
    border: 1px solid #2e283d;
    border-radius: 8px;
    padding: 5px;
}
QPushButton {
    color: #f4f0ff;
    background: #2b253b;
    border: 1px solid #473d5b;
    border-radius: 8px;
    min-height: 24px;
    padding: 7px 16px;
    font-weight: 600;
}
QPushButton:hover { background: #372d4c; border-color: #695784; }
QPushButton:focus, QLineEdit:focus { border-color: #d3b7ff; }
QPushButton[primary="true"] {
    color: #191127;
    background: #bb9dff;
    border-color: #bb9dff;
}
QPushButton[primary="true"]:hover { background: #cfb8ff; }
QPushButton[recording="true"] {
    color: #2f1324;
    background: #ff94af;
    border-color: #ff94af;
}
QPushButton[recording="true"]:hover { background: #ffb3c7; }
QPushButton#recordingMode { padding: 4px 10px; }
QPushButton#recordingMode:checked { background: #493660; border-color: #bb9dff; color: #f4f0ff; }
QPushButton#recordingMode:checked:disabled { background: #352945; border-color: #695784; }
QFrame#webcamPlacement { background: #14121e; border: 1px solid #514467; border-radius: 10px; }
QPushButton#webcamPosition { padding: 4px 12px; font-size: 16px; }
QPushButton#webcamPosition:checked { background: #bb9dff; border-color: #bb9dff; color: #191127; }
QPushButton#webcamPosition:checked:disabled { background: #45375c; border-color: #514467; color: #d9c4ff; }
QPushButton[primary="true"]:focus, QPushButton[recording="true"]:focus {
    border-color: #f4f0ff;
}
QPushButton:pressed, QPushButton[primary="true"]:pressed, QPushButton[recording="true"]:pressed {
    background: #8e72c7;
    border-color: #8e72c7;
}
QPushButton:disabled, QPushButton[primary="true"]:disabled, QPushButton[recording="true"]:disabled {
    color: #aba3bf;
    background: #322b41;
    border-color: #443952;
}
QLineEdit {
    background: #14121e;
    border: 1px solid #433952;
    border-radius: 8px;
    padding: 8px 10px;
    color: #f4f0ff;
    selection-background-color: #785db4;
    font-family: Consolas;
}
QComboBox {
    background: #14121e;
    border: 1px solid #433952;
    border-radius: 8px;
    min-height: 22px;
    padding: 6px 10px;
}
QComboBox:focus { border-color: #d3b7ff; }
QComboBox:disabled { color: #aba3bf; background: #211b2c; }
QComboBox QAbstractItemView, QListWidget {
    background: #211b2c;
    color: #f4f0ff;
    selection-background-color: #5a417f;
    selection-color: #ffffff;
    outline: 0;
}
QListWidget {
    border: 1px solid #433952;
    border-radius: 8px;
    alternate-background-color: #282237;
    padding: 4px;
}
QListWidget::item { padding: 6px 8px; }
QScrollArea#recordingScroll { border: 0; background: transparent; }
QWidget#recordingSidebar { background: #12121b; }
QScrollBar:vertical { width: 9px; background: #12121b; margin: 0; }
QScrollBar::handle:vertical { min-height: 28px; background: #514368; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSlider::groove:horizontal {
    height: 5px;
    border-radius: 2px;
    background: #382f4b;
}
QSlider::sub-page:horizontal { background: #ad8cf8; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 13px;
    margin: -5px 0;
    border: 1px solid #e1ceff;
    border-radius: 7px;
    background: #ba9aff;
}
QProgressBar { background: #30263f; border: 0; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #ba9aff; border-radius: 3px; }
QProgressBar#micLevel { min-height: 8px; max-height: 8px; border-radius: 4px; }
QProgressBar#micLevel::chunk { background: #79d9ae; border-radius: 4px; }
"""
