"""Живой предпросмотр веб-камеры без создания видеофайла."""

from PyQt5.QtCore import QProcess, QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from webcam_capture import DEFAULT_WEBCAM_SIZE, webcam_frame_filter, webcam_frame_size
from webcam_stream import SegmentedWebcam, segmented_input_args


FRAME_PADDING = 16


def preview_args(device, border_style, border_color, size=DEFAULT_WEBCAM_SIZE, segmented_port=None):
    width, height = webcam_frame_size(size)
    frame = webcam_frame_filter(width, height, border_style, border_color)
    source = segmented_input_args(segmented_port) if segmented_port else ["-f", "dshow", "-i", f"video={device}"]
    return [
        "-hide_banner", "-nostdin", "-loglevel", "error",
        *source, "-an",
        "-vf", f"{frame},pad={width + FRAME_PADDING}:{height + FRAME_PADDING}:(ow-iw)/2:(oh-ih)/2:color=0x14121e",
        "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]


class WebcamPreviewDialog(QDialog):
    def __init__(
        self, device, border_style, border_color, parent, size=DEFAULT_WEBCAM_SIZE,
        background="",
    ):
        super().__init__(parent)
        width, height = webcam_frame_size(size)
        self.preview_width = width + FRAME_PADDING
        self.preview_height = height + FRAME_PADDING
        self.frame_bytes = self.preview_width * self.preview_height * 3
        self.setWindowTitle("Проверка веб-камеры")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        self.preview = QLabel()
        self.preview.setFixedSize(self.preview_width, self.preview_height)
        self.preview.setStyleSheet("background: #14121e;")
        self.preview.setAccessibleName("Предпросмотр выбранной веб-камеры")
        layout.addWidget(self.preview)
        self.status = QLabel("Подключение к камере…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        layout.addWidget(close, alignment=Qt.AlignRight)

        self.buffer = bytearray()
        self.pending_result = None
        self.preview_failed = False
        self.segmented_webcam = None
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_frames)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._timed_out)
        if background:
            self.segmented_webcam = SegmentedWebcam(device, background, self)
            self.segmented_webcam.ready.connect(
                lambda port: self.process.start("ffmpeg", preview_args(device, border_style, border_color, size, port))
            )
            self.segmented_webcam.failed.connect(self._background_failed)
            self.segmented_webcam.start()
        else:
            self.process.start("ffmpeg", preview_args(device, border_style, border_color, size))
        self.timeout.start(8000)

    def _read_frames(self):
        data = bytes(self.process.readAllStandardOutput())
        if self.preview_failed:
            return
        self.buffer.extend(data)
        complete = len(self.buffer) // self.frame_bytes * self.frame_bytes
        if complete:
            data = bytes(self.buffer[complete - self.frame_bytes:complete])
            del self.buffer[:complete]
            image = QImage(
                data, self.preview_width, self.preview_height, self.preview_width * 3, QImage.Format_RGB888,
            )
            self.preview.setPixmap(QPixmap.fromImage(image))
            self.status.setText("Веб-камера работает.")
            self.timeout.stop()

    def _timed_out(self):
        self._fail_preview("Камера не передала изображение.")

    def _background_failed(self, details):
        self._fail_preview("Не удалось заменить фон веб-камеры. Проверьте выбранную картинку и камеру.", details)

    def _fail_preview(self, message, details=""):
        self.preview_failed = True
        self.timeout.stop()
        self.status.setText(message)
        self.status.setToolTip(details)
        self._stop_segmented_webcam()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._fail_preview("Не удалось запустить проверку камеры.")

    def _finished(self):
        self.timeout.stop()
        self._stop_segmented_webcam()
        if self.pending_result is not None:
            super().done(self.pending_result)
        elif not self.preview_failed:
            self.status.setText("Изображение недоступно. Проверьте камеру, разрешения Windows и настройки фона.")
            self.status.setToolTip(bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace").strip())

    def done(self, result):
        self._stop_segmented_webcam()
        if self.process.state() == QProcess.NotRunning:
            super().done(result)
        else:
            self.pending_result = result
            self.process.kill()

    def _stop_segmented_webcam(self):
        if self.segmented_webcam is not None:
            self.segmented_webcam.stop()
            self.segmented_webcam = None
