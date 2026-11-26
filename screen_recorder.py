"""Запись экрана Windows через FFmpeg и обработка F12 в фоне."""

import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import re
from shutil import rmtree
from tempfile import mkdtemp
from time import monotonic, time
from uuid import uuid4

from PyQt5.QtCore import QObject, QProcess, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QLabel

from logger import logger
from recording_audio import AudioCapture, SOURCES, mux_audio_args
from recording_segments import JoinSegments
from recording_settings import RecordingSettings, default_recording_directory
from webcam_capture import (
    DEFAULT_WEBCAM_BORDER_COLOR, DEFAULT_WEBCAM_BORDER_STYLE, DEFAULT_WEBCAM_POSITION, webcam_overlay,
)


TARGET_FPS = 60
WM_INPUT = 0x00FF
VK_F12 = 0x7B
VK_F9 = 0x78
RIDEV_INPUTSINK = 0x0100
RID_INPUT = 0x10000003
RI_KEY_BREAK = 0x0001
WDA_EXCLUDEFROMCAPTURE = 0x11
CAPTURE_CLOCK = re.compile(rb"showinfo@capture_clock[^\r\n]*?\bpts:\s*(\d+)")
NO_RECORDED_FRAMES = "Запись отменена до получения первого кадра."


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
        self.keys_down = set()

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
        if read != ctypes.sizeof(raw) or raw.header.type != 1 or raw.virtual_key not in (VK_F9, VK_F12):
            return False
        key = raw.virtual_key
        if raw.flags & RI_KEY_BREAK:
            self.keys_down.discard(key)
        elif key not in self.keys_down:
            self.keys_down.add(key)
            return key
        return False


def recording_args(
    path, audio=False, camera="", position=DEFAULT_WEBCAM_POSITION,
    border_style=DEFAULT_WEBCAM_BORDER_STYLE, border_color=DEFAULT_WEBCAM_BORDER_COLOR,
):
    capture = (
        f"ddagrab=output_idx=0:framerate={TARGET_FPS}:draw_mouse=0,"
        "hwdownload,format=bgra,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    if camera:
        capture = webcam_overlay(capture, position, border_style, border_color)
    graph = f"{capture}[screen]"
    if audio:
        # Timestamp only the first frame. The clock branch must reach EOF so
        # it cannot keep the live webcam input running when FFmpeg stops.
        graph = (
            f"{capture},split[screen][clock];[clock]trim=end_frame=1,"
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
        self.video_probe = QProcess(self)
        self.video_probe.finished.connect(self._on_video_probe_finished)
        self.video_probe.errorOccurred.connect(self._on_video_probe_error)
        self.settings = settings if settings is not None else RecordingSettings(default_recording_directory())
        self.work_dir = None
        self.join_job = None
        self.segments = []
        self.session_warnings = []
        self.keep_work_dir = False
        self.paused = False
        self.pausing = False
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
        self.segments = []
        self.session_warnings = []
        self.keep_work_dir = False
        self.paused = False
        self.pausing = False
        self._start_segment()

    def _start_segment(self):
        try:
            self.segment_dir = Path(mkdtemp(prefix="capture-", dir=self.work_dir))
        except OSError as error:
            self._segment_failed(f"Не удалось подготовить фрагмент записи. {error}")
            return
        self.partial_path = self.segment_dir / "video.mp4"
        self.mixed_path = self.segment_dir / "mixed.mp4"
        self.stopping = False
        self.video_started = False
        self.video_result = None
        self.video_warning = ""
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
            self.audio_job = AudioCapture(self.segment_dir, selections, self)
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
            options["border_style"] = self.settings.webcam_border_style
            options["border_color"] = self.settings.webcam_border_color
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
                self._segment_failed(NO_RECORDED_FRAMES)
            else:
                self._start_video()

    def stop(self):
        if not self.active:
            return
        if self.paused:
            self._finish_segments()
        elif self.pausing:
            self.pausing = False
            self.status_changed.emit("Сохранение записи…")
        elif not self.stopping:
            self._stop_segment()

    def toggle_pause(self):
        if not self.active:
            return
        if self.paused:
            self.paused = False
            self._start_segment()
        elif not self.stopping:
            self.pausing = True
            self._stop_segment()

    def _stop_segment(self):
        self.stopping = True
        message = "Постановка на паузу…" if self.pausing else "Сохранение записи…"
        self.status_changed.emit(message)
        self._show_overlay(message)
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
                self._complete_video(False, NO_RECORDED_FRAMES)
                return
            self._retry_without_webcam()
            return
        self.overlay.hide()
        if exit_status == QProcess.NormalExit and exit_code == 0:
            self._complete_video(bool(self.frame_count), NO_RECORDED_FRAMES)
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
        if success:
            self._save_recorded_video()
        elif self.frame_count and self.partial_path.is_file():
            # FFmpeg can close a playable MP4 even after losing the DXGI output.
            self.status_changed.emit("Проверка записанного фрагмента…")
            self.video_probe.start("ffprobe", [
                "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
                "-of", "csv=p=0", str(self.partial_path),
            ])
        else:
            self._segment_failed(message)

    def _on_video_probe_finished(self, code, status):
        output = bytes(self.video_probe.readAllStandardOutput()).strip()
        if status == QProcess.NormalExit and code == 0 and output == b"video":
            self.video_warning = "Захват экрана прервался. Сохранён записанный фрагмент."
            self._save_recorded_video()
        else:
            self._keep_incomplete_video()

    def _on_video_probe_error(self, error):
        if error == QProcess.FailedToStart:
            self._keep_incomplete_video()

    def _keep_incomplete_video(self):
        _, message = self.video_result
        self._segment_failed(f"{message}\nНезавершённые файлы: {self.work_dir}", cleanup=False)

    def _save_recorded_video(self):
        if self.audio_tracks:
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
        notices = [notice for notice in (warning, self.video_warning, self.webcam_warning) if notice]
        if self.audio_errors:
            sources = ", ".join(SOURCES[source] for source in self.audio_errors)
            notices.append(f"Предупреждение по аудио: {sources}.")
            logger.warning(f"Проблемы захвата аудио: {self.audio_errors}")
        self.keep_work_dir = self.keep_work_dir or not cleanup
        self.session_warnings.extend(notices)
        if self.pausing or self.segments:
            self.segments.append((path, path == self.mixed_path))
            if self.pausing:
                self._enter_pause()
            else:
                self._finish_segments()
        else:
            self._publish_final(path)

    def _segment_failed(self, message, cleanup=True):
        self.keep_work_dir = self.keep_work_dir or not cleanup
        if self.pausing:
            if message != NO_RECORDED_FRAMES:
                self.session_warnings.append(message)
            self._enter_pause()
        elif self.segments:
            if message != NO_RECORDED_FRAMES:
                self.session_warnings.append(message)
            self._finish_segments()
        else:
            self._finish_session(message, cleanup=not self.keep_work_dir)

    def _enter_pause(self):
        self.pausing = False
        self.paused = True
        self.stopping = False
        self.status_changed.emit("Запись на паузе. F9 — продолжить, F12 — завершить.")
        self._show_overlay("Ⅱ ПАУЗА  |  F9 — продолжить")

    def _finish_segments(self):
        self.paused = False
        self.pausing = False
        self.stopping = True
        if not self.segments:
            self._finish_session(NO_RECORDED_FRAMES, cleanup=not self.keep_work_dir)
        elif len(self.segments) == 1:
            self._publish_final(self.segments[0][0])
        else:
            self.status_changed.emit("Объединение фрагментов записи…")
            self._show_overlay("Объединение фрагментов…")
            self.join_job = JoinSegments(tuple(self.segments), self.work_dir / "joined.mp4", self)
            self.join_job.finished.connect(self._on_segments_joined)
            self.join_job.start()

    def _on_segments_joined(self):
        job = self.join_job
        self.join_job = None
        if job.error:
            logger.error(f"Не удалось объединить фрагменты: {job.error}")
            self._finish_session(f"Не удалось объединить запись. Фрагменты сохранены в {self.work_dir}", cleanup=False)
        else:
            self._publish_final(job.output)
        job.deleteLater()

    def _publish_final(self, path):
        try:
            path.rename(self.output_path)
        except OSError as error:
            self._finish_session(f"Не удалось переместить готовый файл {path}. {error}", cleanup=False)
            return
        message = f"Запись сохранена.\n{self.output_path}"
        for notice in dict.fromkeys(self.session_warnings):
            message += f"\n{notice}"
        logger.info(f"Запись экрана сохранена: {self.output_path}")
        self._finish_session(message, cleanup=not self.keep_work_dir)

    def _finish_session(self, message, cleanup=True):
        directory = self.work_dir
        self.work_dir = None
        self.segments = []
        self.paused = False
        self.pausing = False
        self.overlay.hide()
        if cleanup:
            try:
                rmtree(directory)
            except OSError as error:
                logger.warning(f"Не удалось убрать временные файлы записи: {error}")
        self.status_changed.emit(message)
        self.finished.emit()

    def _report_error(self, message):
        self.status_changed.emit(message)
        logger.error(message)
