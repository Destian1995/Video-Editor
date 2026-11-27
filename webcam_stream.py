"""Run the camera decoder and background processor for preview or recording."""

from pathlib import Path
import sys

from PyQt5.QtCore import QCoreApplication, QObject, QProcess, pyqtSignal

from webcam_capture import SEGMENTED_FPS as FPS, SEGMENTED_HEIGHT as HEIGHT, SEGMENTED_WIDTH as WIDTH


def segmented_input_args(port):
    return [
        "-rw_timeout", "5000000", "-f", "rawvideo", "-pixel_format", "bgr24",
        "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS),
        "-i", f"tcp://127.0.0.1:{port}",
    ]


def camera_decoder_args(device):
    return [
        "-hide_banner", "-nostdin", "-loglevel", "error", "-rtbufsize", "8M",
        "-f", "dshow", "-i", f"video={device}", "-an",
        "-vf", (
            f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"format=bgr24,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        ),
        "-c:v", "rawvideo", "-threads:v", "1", "-f", "rawvideo", "pipe:1",
    ]


class SegmentedWebcam(QObject):
    ready = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, device, background, parent):
        super().__init__(parent)
        self.capture = QProcess(self)
        self.worker = QProcess(self)
        self.capture.setStandardOutputProcess(self.worker)
        self.capture.setProgram("ffmpeg")
        self.capture.setArguments(camera_decoder_args(device))
        self.worker.setProgram(sys.executable)
        self.worker.setArguments([str(Path(__file__).with_name("webcam_segmenter.py")), background])
        self.worker.readyReadStandardOutput.connect(self._read_port)
        self.worker.finished.connect(self._worker_finished)
        self.worker.errorOccurred.connect(self._worker_error)
        self.capture.errorOccurred.connect(self._capture_error)
        self.capture.finished.connect(self._capture_finished)
        self.port_line = b""
        self.stopping = False

    def start(self):
        self.worker.start()

    def _read_port(self):
        self.port_line += bytes(self.worker.readAllStandardOutput())
        if not self.stopping and self.port_line.endswith(b"\n"):
            self.capture.start()
            self.ready.emit(int(self.port_line))

    def _worker_finished(self, code, status):
        if not self.stopping and (code or status != QProcess.NormalExit or not self.port_line):
            self.failed.emit(self._error_details())
        self._dispose()

    def _capture_finished(self, code, status):
        if not self.stopping and (code or status != QProcess.NormalExit):
            self.failed.emit(self._error_details())
        self._dispose()

    def _worker_error(self, error):
        if not self.stopping and error == QProcess.FailedToStart:
            self.failed.emit(self.worker.errorString())
        self._dispose()

    def _capture_error(self, error):
        if not self.stopping and error == QProcess.FailedToStart:
            self.failed.emit(self.capture.errorString())
        self._dispose()

    def _error_details(self):
        worker_error = bytes(self.worker.readAllStandardError())
        camera_error = bytes(self.capture.readAllStandardError())
        return (worker_error + camera_error).decode("utf-8", errors="replace").strip()

    def stop(self):
        self.stopping = True
        self.setParent(QCoreApplication.instance())
        for process in (self.capture, self.worker):
            if process.state() != QProcess.NotRunning:
                process.kill()
        self._dispose()

    def _dispose(self):
        if self.stopping and all(p.state() == QProcess.NotRunning for p in (self.capture, self.worker)):
            self.deleteLater()
