"""Запись экрана Windows через FFmpeg и обработка F12 в фоне."""

import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import re
from tempfile import mkdtemp
from time import monotonic, time
from uuid import uuid4

from PyQt5.QtCore import QObject, QProcess, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QLabel

from logger import logger
from recording_audio import AudioCapture, SOURCES, mux_audio_args
from recording_settings import RecordingSettings, default_recording_directory
from webcam_capture import DEFAULT_WEBCAM_POSITION, webcam_overlay


TARGET_FPS = 60
WM_INPUT = 0x00FF
VK_F12 = 0x7B
RIDEV_INPUTSINK = 0x0100
RID_INPUT = 0x10000003
RI_KEY_BREAK = 0x0001
WDA_EXCLUDEFROMCAPTURE = 0x11
CAPTURE_CLOCK = re.compile(rb"showinfo@capture_clock[^\r\n]*?\bpts:\s*(\d+)")


class RawInputDevice(ctypes.Structure):
    _fields_ = [
        ("usage_page", wintypes.USHORT), ("usage", wintypes.USHORT),
        ("flags", wintypes.DWORD), ("target", wintypes.HWND),
    ]


class RawInputHeader(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD), ("size", wintypes.DWORD),
        ("device", wintypes.HANDLE), ("wparam", wintypes.WPARAM),
    ]


class RawKeyboardInput(ctypes.Structure):
    _fields_ = [
        ("header", RawInputHeader),
        ("scan_code", wintypes.USHORT), ("flags", wintypes.USHORT),
        ("reserved", wintypes.USHORT), ("virtual_key", wintypes.USHORT),
        ("message", wintypes.UINT), ("extra_information", wintypes.ULONG),
    ]


class RecordingHotkey:
    def __init__(self, window_id):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        register = self.user32.RegisterRawInputDevices
        register.argtypes = [
            ctypes.POINTER(RawInputDevice), wintypes.UINT, wintypes.UINT,
        ]
        register.restype = wintypes.BOOL
        keyboard = RawInputDevice(0x01, 0x06, RIDEV_INPUTSINK, window_id)
        if not register(ctypes.byref(keyboard), 1, ctypes.sizeof(keyboard)):
            raise ctypes.WinError(ctypes.get_last_error())

        self.read_input = self.user32.GetRawInputData
        self.read_input.argtypes = [
            wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
            ctypes.POINTER(wintypes.UINT), wintypes.UINT,
        ]
        self.read_input.restype = wintypes.UINT
        self.f12_down = False

    def pressed(self, event_type, message):
        if event_type != b"windows_generic_MSG":
            return False
        event = wintypes.MSG.from_address(int(message))
        if event.message != WM_INPUT:
            return False

        raw = RawKeyboardInput()
        size = wintypes.UINT(ctypes.sizeof(raw))
        read = self.read_input(
            event.lParam, RID_INPUT, ctypes.byref(raw),
            ctypes.byref(size), ctypes.sizeof(RawInputHeader),
        )
        if read != ctypes.sizeof(raw) or raw.header.type != 1 or raw.virtual_key != VK_F12:
            return False
        was_down = self.f12_down
        self.f12_down = not bool(raw.flags & RI_KEY_BREAK)
        return self.f12_down and not was_down


def recording_args(path, audio=False, camera="", position=DEFAULT_WEBCAM_POSITION):
    capture = (
        f"ddagrab=output_idx=0:framerate={TARGET_FPS}:draw_mouse=0,"
        "hwdownload,format=bgra,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    if camera:
        capture = webcam_overlay(capture, position)
    graph = f"{capture}[screen]"
    if audio:
        # Timestamp the first frame with the same clock used by the audio callbacks.
        graph = (
            f"{capture},split[screen][clock];[clock]select=eq(n\\,0),"
            "settb=1/1000000,setpts=RTCTIME,showinfo@capture_clock,nullsink"
        )
    args = [
        "-hide_banner", "-loglevel", "info" if audio else "warning", "-nostats", "-n",
        "-stats_period", "1", "-progress", "pipe:1",
    ]
    if camera:
        args += [
            "-thread_queue_size", "32", "-rtbufsize", "64M", "-f", "dshow", "-analyzeduration", "0",
            "-i", f"video={camera}",
        ]
    args += [
        "-filter_complex", graph, "-map", "[screen]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-g", str(TARGET_FPS * 2), "-fps_mode", "vfr",
    ]
    if not audio:
        args += ["-movflags", "+faststart"]
    return args + ["-f", "mp4", str(path)]


class ScreenRecorder(QObject):
    status_changed = pyqtSignal(str)
    audio_changed = pyqtSignal()
    webcam_changed = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, parent, settings=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.started.connect(self._on_started)
        self.process.readyReadStandardOutput.connect(self._read_progress)
        self.process.readyReadStandardError.connect(self._read_errors)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_process_error)
        self.webcam_timeout = QTimer(self)
        self.webcam_timeout.setSingleShot(True)
        self.webcam_timeout.timeout.connect(self._on_webcam_timeout)
        self.mux = QProcess(self)
        self.mux.finished.connect(self._on_mux_finished)
        self.mux.errorOccurred.connect(self._on_mux_error)
        self.settings = settings if settings is not None else RecordingSettings(default_recording_directory())
        self.work_dir = None
        self.audio_job = None
        self.audio_names = {}
        self.audio_errors = {}
        self.audio_resolved = False
        self.webcam_in_use = False
        self.webcam_warning = ""
        self.stopping = False
        self.output_path = None
        self.partial_path = None
        self.progress_buffer = b""
        self.error_buffer = b""
        self.frame_count = 0
        self.fps_sample = None

        self.overlay = QLabel(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus,
        )
        self.overlay.setAttribute(Qt.WA_ShowWithoutActivating)
        self.overlay.setStyleSheet(
            "QLabel { background: #25192e; color: #ffd6e2; padding: 8px 12px; "
            "border: 1px solid #79425d; font: bold 14px 'Segoe UI'; }"
        )
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        exclude = user32.SetWindowDisplayAffinity
        exclude.argtypes = [wintypes.HWND, wintypes.DWORD]
        exclude.restype = wintypes.BOOL
        if not exclude(int(self.overlay.winId()), WDA_EXCLUDEFROMCAPTURE):
            logger.warning("Windows не смогла исключить индикатор из захвата")

    @property
    def active(self):
        return self.work_dir is not None

    def toggle(self):
        if self.active:
            self.stop()
        else:
            self.start()

    def start(self):
        directory = self.settings.directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.work_dir = Path(mkdtemp(prefix=".video-editor-", dir=directory))
        except OSError as error:
            self._report_error(f"Не удалось создать папку записей. {error}")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name = f"game_{timestamp}_{uuid4().hex}"
        self.output_path = directory / f"{name}.mp4"
        self.partial_path = self.work_dir / "video.mp4"
        self.mixed_path = self.work_dir / "mixed.mp4"
        self.stopping = False
        self.video_started = False
        self.video_result = None
        self.video_start = None
        self.audio_names = {}
        self.audio_errors = {}
        self.audio_tracks = {}
        self.audio_resolved = False
        self.webcam_in_use = self.settings.webcam_enabled and bool(self.settings.webcam_device)
        self.webcam_warning = ""
        if self.settings.webcam_enabled and not self.settings.webcam_device:
            self.webcam_warning = "Веб-камера не выбрана. Видео записано без вставки."
        self.progress_buffer = b""
        self.error_buffer = b""
        self.frame_count = 0
        self.fps_sample = None
        self.status_changed.emit("Запуск записи…")
        self._show_overlay("Запуск записи…")
        self.audio_changed.emit()
        self.webcam_changed.emit()
        selections = self.settings.audio_selections()
        if selections:
            self.audio_job = AudioCapture(self.work_dir, selections, self)
            self.audio_job.ready.connect(self._on_audio_ready)
            self.audio_job.finished.connect(self._on_audio_finished)
            self.audio_job.start()
        else:
            self._start_video()

    def _on_audio_ready(self, names, errors):
        self.audio_names = names
        self.audio_errors = errors
        self.audio_resolved = True
        self.audio_changed.emit()
        if not self.stopping:
            self._start_video()

    def _start_video(self):
        self.video_started = True
        self.video_launch_time = time()
        options = {"audio": bool(self.audio_names)}
        if self.webcam_in_use:
            options["camera"] = self.settings.webcam_device
            options["position"] = self.settings.webcam_position
            self.webcam_timeout.start(12000)
        self.process.start("ffmpeg", recording_args(self.partial_path, **options))

    def _on_webcam_timeout(self):
        if self.webcam_in_use and not self.frame_count and self.process.state() != QProcess.NotRunning:
            self.process.kill()

    def _on_audio_finished(self):
        job = self.audio_job
        self.audio_job = None
        self.audio_tracks = job.tracks
        self.audio_errors = job.errors
        self.audio_names = {source: name for source, name in self.audio_names.items() if source in self.audio_tracks}
        self.audio_resolved = True
        job.deleteLater()
        self.audio_changed.emit()
        if self.video_result is not None:
            self._finalize_video()
        elif not self.video_started:
            if self.stopping:
                self._finish_session("Запись отменена до получения первого кадра.")
            else:
                self._start_video()

    def stop(self):
        if not self.active or self.stopping:
            return
        self.stopping = True
        self.status_changed.emit("Сохранение записи…")
        self._show_overlay("Сохранение записи…")
        if not self.video_started and self.audio_job:
            self.audio_job.stop()
        if self.process.state() == QProcess.Running:
            self._request_ffmpeg_stop()

    def _on_started(self):
        if self.stopping:
            self._request_ffmpeg_stop()

    def _request_ffmpeg_stop(self):
        # FFmpeg завершает MP4 и записывает его индекс после команды q.
        self.process.write(b"q\n")
        self.process.closeWriteChannel()

    def _show_overlay(self, text):
        self.overlay.setText(text)
        self.overlay.adjustSize()
        origin = QApplication.primaryScreen().geometry().topLeft()
        self.overlay.move(origin.x() + 12, origin.y() + 12)
        self.overlay.show()

    def _read_progress(self):
        chunk = self.progress_buffer + bytes(self.process.readAllStandardOutput())
        *lines, self.progress_buffer = chunk.split(b"\n")
        for line in lines:
            key, _, value = line.strip().partition(b"=")
            if key == b"frame":
                self.frame_count = int(value)
                if self.frame_count:
                    self.webcam_timeout.stop()
            elif key == b"progress" and value == b"continue" and self.frame_count:
                self._update_fps()

    def _update_fps(self):
        now = monotonic()
        first_sample = self.fps_sample is None
        fps_text = "—"
        if not first_sample:
            previous_count, previous_time = self.fps_sample
            if now - previous_time < 0.5:
                return
            fps_text = f"{(self.frame_count - previous_count) / (now - previous_time):.0f}"
        self.fps_sample = (self.frame_count, now)
        if not self.stopping:
            if first_sample:
                self.status_changed.emit("Идёт запись.")
            self._show_overlay(f"● REC  |  {fps_text} FPS записи")

    def _read_errors(self):
        chunk = bytes(self.process.readAllStandardError())
        contents = self.error_buffer + chunk
        if self.audio_names and self.video_start is None:
            match = CAPTURE_CLOCK.search(contents)
            if match:
                self.video_start = int(match.group(1)) / 1_000_000
        self.error_buffer = contents[-8192:]

    def _on_process_error(self, error):
        if error == QProcess.FailedToStart:
            self.webcam_timeout.stop()
            self._complete_video(False, f"Не удалось запустить FFmpeg. {self.process.errorString()}")

    def _on_finished(self, exit_code, exit_status):
        self.webcam_timeout.stop()
        self._read_progress()
        self._read_errors()
        if self.webcam_in_use and not self.frame_count:
            if self.stopping:
                self._complete_video(False, "Запись отменена до получения первого кадра.")
                return
            self._retry_without_webcam()
            return
        self.overlay.hide()
        if exit_status == QProcess.NormalExit and exit_code == 0:
            self._complete_video(bool(self.frame_count), "Запись отменена до получения первого кадра.")
        else:
            details = self.error_buffer.decode("utf-8", errors="replace").strip()
            if details:
                logger.error(f"FFmpeg завершил запись с ошибкой: {details}")
            self._complete_video(
                False, "Захват завершился с ошибкой. Проверьте FFmpeg и попробуйте оконный режим без рамки."
            )

    def _retry_without_webcam(self):
        logger.warning(f"Запуск с веб-камерой не удался: {self.error_buffer.decode('utf-8', errors='replace')}")
        try:
            self.partial_path.unlink(missing_ok=True)
        except OSError as error:
            self._complete_video(False, f"Не удалось перезапустить запись без веб-камеры. {error}")
            return
        self.webcam_in_use = False
        self.webcam_warning = "Веб-камера недоступна. Видео записано без вставки."
        self.progress_buffer = b""
        self.error_buffer = b""
        self.video_start = None
        self.webcam_changed.emit()
        self.status_changed.emit("Камера недоступна. Запуск записи экрана…")
        self._start_video()

    def _complete_video(self, success, message):
        self.video_result = (success, message)
        self.stopping = True
        if self.audio_job:
            self.audio_job.stop()
        else:
            self._finalize_video()

    def _finalize_video(self):
        success, message = self.video_result
        if not success:
            keep = bool(self.frame_count and self.partial_path.is_file())
            if keep:
                message += f"\nНезавершённые файлы: {self.work_dir}"
            self._finish_session(message, cleanup=not keep)
        elif self.audio_tracks:
            self.status_changed.emit("Сохранение MP4 со звуком…")
            if self.video_start is None:
                self.video_start = self.video_launch_time
                logger.warning("Точное время первого видеокадра недоступно")
            self.mux.start("ffmpeg", mux_audio_args(
                self.partial_path, self.mixed_path, self.audio_tracks, self.video_start,
                self.settings.microphone_gain_db,
            ))
        else:
            self._publish(self.partial_path)

    def _on_mux_finished(self, code, status):
        if status == QProcess.NormalExit and code == 0:
            self._publish(self.mixed_path)
        else:
            details = bytes(self.mux.readAllStandardError()).decode("utf-8", errors="replace")
            self._mux_failed(details)

    def _on_mux_error(self, error):
        if error == QProcess.FailedToStart:
            self._mux_failed(self.mux.errorString())

    def _mux_failed(self, details):
        logger.error(f"Не удалось добавить звук: {details}")
        for source in self.audio_tracks:
            self.audio_errors[source] = "дорожка не добавлена в MP4"
        self.audio_names.clear()
        self.audio_changed.emit()
        self._publish(
            self.partial_path, f"Звук не удалось добавить. Исходные дорожки: {self.work_dir}",
            cleanup=False,
        )

    def _publish(self, path, warning="", cleanup=True):
        try:
            path.rename(self.output_path)
        except OSError as error:
            self._finish_session(f"Не удалось переместить готовый файл {path}. {error}", cleanup=False)
            return
        message = f"Запись сохранена.\n{self.output_path}"
        if warning:
            message += f"\n{warning}"
        if self.webcam_warning:
            message += f"\n{self.webcam_warning}"
        if self.audio_errors:
            sources = ", ".join(SOURCES[source] for source in self.audio_errors)
            message += f"\nПредупреждение по аудио: {sources}."
            logger.warning(f"Проблемы захвата аудио: {self.audio_errors}")
        logger.info(f"Запись экрана сохранена: {self.output_path}")
        self._finish_session(message, cleanup)

    def _finish_session(self, message, cleanup=True):
        directory = self.work_dir
        self.work_dir = None
        self.overlay.hide()
        if cleanup:
            try:
                for name in ("video.mp4", "mixed.mp4", "game.pcm", "microphone.pcm"):
                    (directory / name).unlink(missing_ok=True)
                directory.rmdir()
            except OSError as error:
                logger.warning(f"Не удалось убрать временные файлы записи: {error}")
        self.status_changed.emit(message)
        self.finished.emit()

    def _report_error(self, message):
        self.status_changed.emit(message)
        logger.error(message)
