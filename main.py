from dataclasses import replace
import sys
from pathlib import Path

# Проверка зависимостей перед импортом
from check_dependencies import check_dependencies
check_dependencies()

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QSlider, QLabel, QFileDialog, QMessageBox,
    QButtonGroup, QDialog, QFrame, QLineEdit, QProgressBar, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import QSize, Qt, QSignalBlocker, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QIcon, QImage
from editor_ui import (
    EDITOR_STYLE, CaptureIllustration, EditorTabs, FileLabel, FramePreview,
    RecordingStatus, card, label, recording_mode_icon, style_title_bar,
)
from video_processor import VideoProcessor
from logger import logger
from operation_history import history
from recording_audio import SOURCES
from recording_settings import RecordingPreferences, RecordingSettingsDialog, format_gain
from screen_recorder import TARGET_FPS, VK_F9, VK_F12, RecordingHotkey, ScreenRecorder
from screen_region import RECORDING_MODES, RegionOutline, ScreenRegionSelector, default_capture_region, region_is_available
from webcam_capture import WEBCAM_BORDER_STYLES, WEBCAM_SIZES, webcam_border_style, webcam_position, webcam_size


APP_ICON = Path(__file__).with_name("video-editor.ico")


class VideoTrimThread(QThread):
    """Поток для обрезки видео без блокировки UI"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, processor, input_path, output_path, start_time, end_time):
        super().__init__()
        self.processor = processor
        self.input_path = input_path
        self.output_path = output_path
        self.start_time = start_time
        self.end_time = end_time
    
    def run(self):
        try:
            self.processor.trim_video(
                self.input_path, 
                self.output_path, 
                self.start_time, 
                self.end_time
            )
            self.finished.emit(True, "Видео успешно обрезано!")
        except Exception as e:
            self.finished.emit(False, str(e))


class VideoEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.processor = VideoProcessor()
        self.current_video_path = None
        self.trim_thread = None
        self.recorder = None
        self.recording_hotkey = None
        self.recording_settings_dialog = None
        self.close_after_recording = False
        self.region_selector = None
        self.region_outline = None
        self.region_restore_state = None
        self.region_start_timer = QTimer(self)
        self.region_start_timer.setSingleShot(True)
        self.region_start_timer.timeout.connect(self.start_region_capture)
        
        self.initUI()
        self.setWindowTitle("Video Editor")
        self.setMinimumSize(780, 520)
        self.resize(1160, 740)
        style_title_bar(self)
    
    def initUI(self):
        workspace = QWidget()
        workspace.setObjectName("workspace")
        shell = QVBoxLayout(workspace)
        shell.setContentsMargins(26, 18, 26, 24)
        shell.setSpacing(14)
        self.setCentralWidget(workspace)

        self.tabs = EditorTabs()
        self.tabs.addTab(self.create_recording_tab(), "Запись экрана")
        editor_tab = self.create_editor_tab()
        self.tabs.addTab(editor_tab, "Редактор")
        if sys.platform != "win32":
            self.tabs.setCurrentWidget(editor_tab)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(QIcon(str(APP_ICON)).pixmap(38, 38))
        header.addWidget(icon)
        header.addWidget(label("Video Editor", "brand"))
        header.addStretch()
        if self.recording_hotkey:
            header.addWidget(label("Запуск / остановка записи", "muted"))
            header.addWidget(label("F12", "keycap"))
            header.addSpacing(8)
            header.addWidget(label("Пауза", "muted"))
            header.addWidget(label("F9", "keycap"))
        shell.addLayout(header)
        shell.addWidget(self.tabs, 1)
        self.setStyleSheet(EDITOR_STYLE)

    def create_editor_tab(self):
        tab = QWidget()
        page = QHBoxLayout(tab)
        page.setContentsMargins(0, 16, 0, 0)
        page.setSpacing(16)

        preview, preview_layout = card()
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("Предпросмотр", "sectionTitle"), 1)
        open_button = QPushButton("Открыть видео")
        open_button.clicked.connect(self.load_video)
        toolbar.addWidget(open_button)
        preview_layout.addLayout(toolbar)

        self.frame_label = FramePreview()
        preview_layout.addWidget(self.frame_label, 1)
        self.video_path_label = FileLabel()
        self.video_path_label.hide()
        preview_layout.addWidget(self.video_path_label)

        timeline_header = QHBoxLayout()
        timeline_header.addWidget(label("Временная шкала", "muted"), 1)
        zero = self.processor.format_time(0)
        self.time_label = label(f"{zero} / {zero}", "timecode")
        timeline_header.addWidget(self.time_label)
        preview_layout.addLayout(timeline_header)
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setAccessibleName("Временная шкала")
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self.on_slider_moved)
        preview_layout.addWidget(self.timeline_slider)
        page.addWidget(preview, 1)

        sidebar = QVBoxLayout()
        sidebar.setSpacing(14)
        trim, trim_layout = card()
        trim.setFixedWidth(315)
        trim_layout.addWidget(label("Обрезка видео", "sectionTitle"))
        times = QGridLayout()
        times.setHorizontalSpacing(10)
        times.setVerticalSpacing(6)
        self.start_time_edit = QLineEdit("00:00:00")
        self.end_time_edit = QLineEdit("00:00:00")
        for column, (title, field) in enumerate((
            ("Начало", self.start_time_edit), ("Конец", self.end_time_edit)
        )):
            caption = label(title, "muted")
            caption.setBuddy(field)
            field.setAccessibleName(title)
            field.setPlaceholderText("HH:MM:SS")
            field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            field.setMinimumHeight(36)
            times.addWidget(caption, 0, column)
            times.addWidget(field, 1, column)
        self.start_time_edit.textChanged.connect(self.on_start_time_changed)
        trim_layout.addLayout(times)

        trim_button = QPushButton("Обрезать видео")
        trim_button.setProperty("primary", True)
        trim_button.clicked.connect(self.trim_video)
        trim_layout.addWidget(trim_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName("Обрезка видео")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        trim_layout.addWidget(self.progress_bar)
        sidebar.addWidget(trim)

        info, info_layout = card()
        info.setFixedWidth(315)
        info_layout.addWidget(label("Свойства видео", "sectionTitle"))
        details = QGridLayout()
        details.setColumnStretch(0, 1)
        details.setVerticalSpacing(10)
        self.duration_label = label("—", "value")
        self.resolution_label = label("—", "value")
        self.fps_label = label("—", "value")
        self.codec_label = label("—", "value")
        self.size_label = label("—", "value")
        for row, (caption, value) in enumerate((
            ("Длительность", self.duration_label),
            ("Разрешение", self.resolution_label),
            ("Частота кадров", self.fps_label),
            ("Кодек", self.codec_label),
            ("Размер файла", self.size_label),
        )):
            details.addWidget(label(caption, "muted"), row, 0)
            details.addWidget(value, row, 1, Qt.AlignRight)
        info_layout.addLayout(details)
        sidebar.addWidget(info)
        sidebar.addStretch()
        page.addLayout(sidebar)
        return tab

    def create_recording_tab(self):
        tab = QWidget()
        page = QHBoxLayout(tab)
        page.setContentsMargins(0, 16, 0, 0)
        page.setSpacing(16)
        if sys.platform != "win32":
            notice, notice_layout = card()
            notice_layout.addWidget(label("Запись экрана доступна в Windows.", "sectionTitle"))
            page.addWidget(notice, alignment=Qt.AlignTop)
            return tab

        self.recording_preferences = RecordingPreferences()
        self.recorder = ScreenRecorder(self, self.recording_preferences.load())
        self.recorder.finished.connect(self.on_recording_finished)
        self.recorder.audio_changed.connect(self.update_recording_summary)
        self.recorder.webcam_changed.connect(self.update_recording_summary)
        try:
            self.recording_hotkey = RecordingHotkey(int(self.winId()))
            hint = "F12 запускает и завершает запись. F9 ставит её на паузу и продолжает."
        except OSError as error:
            logger.warning(f"Не удалось настроить F12: {error}")
            hint = "Не удалось настроить F12. Запись доступна по кнопке."

        capture, capture_layout = card()
        capture_header = QHBoxLayout()
        capture_header.addWidget(label("Захват экрана", "sectionTitle"), 1)
        self.capture_state = label("Ожидание", "captureState")
        capture_header.addWidget(self.capture_state)
        capture_layout.addLayout(capture_header)

        mode_row = QHBoxLayout()
        mode_row.addWidget(label("Режим записи", "muted"))
        self.recording_modes = QButtonGroup(self)
        for mode, name in RECORDING_MODES.items():
            button = QPushButton(recording_mode_icon(mode), name)
            button.setObjectName("recordingMode")
            button.setIconSize(QSize(20, 20))
            button.setProperty("mode", mode)
            button.setToolTip("Запись всего экрана" if mode == "game" else "Запись выбранной области экрана")
            button.setCheckable(True)
            self.recording_modes.addButton(button)
            button.setChecked(mode == self.recorder.settings.recording_mode)
            mode_row.addWidget(button)
        self.recording_modes.buttonClicked.connect(self.change_recording_mode)
        mode_row.addStretch()
        capture_layout.addLayout(mode_row)

        self.region_controls = QWidget()
        region_row = QHBoxLayout(self.region_controls)
        region_row.setContentsMargins(0, 0, 0, 0)
        self.region_details = label("", "muted")
        self.region_details.setWordWrap(True)
        self.region_button = QPushButton("Выбрать область…")
        self.region_button.clicked.connect(self.select_recording_region)
        region_row.addWidget(self.region_details, 1)
        region_row.addWidget(self.region_button)
        capture_layout.addWidget(self.region_controls)

        self.capture_illustration = CaptureIllustration()
        capture_layout.addWidget(self.capture_illustration, 1)
        overlay_hint = label("Индикатор REC и FPS появится в левом верхнем углу экрана.", "muted")
        overlay_hint.setWordWrap(True)
        capture_layout.addWidget(overlay_hint)
        page.addWidget(capture, 1)

        scroll = QScrollArea()
        scroll.setObjectName("recordingScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedWidth(335)
        sidebar_widget = QWidget()
        sidebar_widget.setObjectName("recordingSidebar")
        sidebar = QVBoxLayout(sidebar_widget)
        sidebar.setContentsMargins(0, 0, 4, 0)
        sidebar.setSpacing(14)
        controls, controls_layout = card()
        controls_layout.addWidget(label("Управление записью", "sectionTitle"))
        self.recording_button = QPushButton("Начать запись")
        self.recording_button.setProperty("primary", True)
        self.recording_button.clicked.connect(self.toggle_recording)
        recording_actions = QHBoxLayout()
        recording_actions.addWidget(self.recording_button, 1)
        self.pause_button = QPushButton("Пауза")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_recording_pause)
        recording_actions.addWidget(self.pause_button)
        controls_layout.addLayout(recording_actions)
        hint_label = label(hint, "muted")
        hint_label.setWordWrap(True)
        controls_layout.addWidget(hint_label)
        self.recording_status = RecordingStatus("Запись не запущена.")
        self.recorder.status_changed.connect(self.on_recording_status)
        controls_layout.addWidget(self.recording_status)
        self.recording_settings_button = QPushButton("Настройки записи")
        self.recording_settings_button.clicked.connect(self.open_recording_settings)
        controls_layout.addWidget(self.recording_settings_button)
        sidebar.addWidget(controls)

        output, output_layout = card()
        output_layout.addWidget(label("Параметры записи", "sectionTitle"))
        details = QGridLayout()
        details.setColumnStretch(1, 1)
        details.setVerticalSpacing(10)
        self.recording_summary = {}
        fields = [
            ("format", "Формат"), ("fps", "Частота"), ("directory", "Папка"),
            *SOURCES.items(), ("webcam", "Веб-камера"), ("webcam_position", "Положение"),
            ("webcam_size", "Размер камеры"), ("webcam_border", "Рамка"),
        ]
        for row, (field, caption) in enumerate(fields):
            details.addWidget(label(caption, "muted"), row, 0)
            value = FileLabel("value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            details.addWidget(value, row, 1)
            self.recording_summary[field] = value
        output_layout.addLayout(details)
        sidebar.addWidget(output)
        sidebar.addStretch()
        scroll.setWidget(sidebar_widget)
        page.addWidget(scroll)
        self.update_recording_summary()
        settings = self.settings_for_recording_mode(self.recorder.settings.recording_mode)
        if settings != self.recorder.settings:
            self.save_capture_selection(settings)
        else:
            self.update_region_controls()
        return tab

    def open_recording_settings(self):
        if (
            self.recorder.active or self.region_selector is not None
            or self.region_start_timer.isActive() or self.recording_settings_dialog is not None
        ):
            return
        dialog = RecordingSettingsDialog(self.recording_preferences, self.recorder.settings, self)
        self.recording_settings_dialog = dialog
        self.recorder.hide_overlay()
        try:
            if dialog.exec_() == QDialog.Accepted:
                self.recorder.settings = dialog.result_settings
                self.recorder.audio_names = {}
                self.recorder.audio_errors = {}
                self.recorder.audio_resolved = False
                self.recorder.webcam_warning = ""
                self.update_recording_summary()
        finally:
            self.recording_settings_dialog = None
            dialog.deleteLater()
            self.update_ready_overlay()

    def update_recording_summary(self):
        settings = self.recorder.settings
        summary = self.recording_summary
        selections = settings.audio_selections()
        names = self.recorder.audio_names
        errors = self.recorder.audio_errors
        has_audio = bool(names if self.recorder.audio_resolved else selections)
        summary["format"].set_full_text("MP4 · H.264 / AAC" if has_audio else "MP4 · H.264")
        summary["fps"].set_full_text(f"{TARGET_FPS} FPS (цель)")
        summary["directory"].set_full_text(str(settings.directory))
        if not settings.webcam_enabled:
            summary["webcam"].set_full_text("Выключена")
            summary["webcam_position"].set_full_text("—")
            summary["webcam_size"].set_full_text("—")
            summary["webcam_border"].set_full_text("—")
        elif self.recorder.webcam_warning:
            summary["webcam"].set_full_text("Недоступна", self.recorder.webcam_warning)
            summary["webcam_position"].set_full_text("—")
            summary["webcam_size"].set_full_text("—")
            summary["webcam_border"].set_full_text("—")
        else:
            summary["webcam"].set_full_text(settings.webcam_name or "Камера")
            summary["webcam_position"].set_full_text(webcam_position(settings.webcam_position)[0])
            summary["webcam_size"].set_full_text(WEBCAM_SIZES[webcam_size(settings.webcam_size)][0])
            name, layers = WEBCAM_BORDER_STYLES[webcam_border_style(settings.webcam_border_style)]
            if layers:
                name = f"{name} · {settings.webcam_border_color.upper()}"
            summary["webcam_border"].set_full_text(name)
        for source in SOURCES:
            if source not in selections:
                text = "Выключен"
            elif source in errors:
                text = "Проверьте источник" if source in names else "Недоступно"
            else:
                text = names.get(source) or selections[source] or "По умолчанию"
                if source == "microphone":
                    text = f"{text} · {format_gain(settings.microphone_gain_db)}"
            tooltip = f"{names.get(source, '')} · {errors[source]}".lstrip(" ·") if source in errors else text
            summary[source].set_full_text(text, tooltip)

    def toggle_recording(self):
        if self.close_after_recording or self.recording_settings_dialog is not None or self.region_selector is not None:
            return
        if self.region_start_timer.isActive():
            self.region_start_timer.stop()
            self.restore_region_window()
        elif not self.recorder.active and self.recorder.settings.recording_mode == "region":
            if region_is_available(self.recorder.settings.capture_region):
                self.prepare_region_capture(self.windowState())
            else:
                self.select_recording_region(start_after_selection=True)
        else:
            self.recorder.toggle()
        self.update_recording_controls()

    def change_recording_mode(self, button):
        self.save_capture_selection(self.settings_for_recording_mode(button.property("mode")))

    def settings_for_recording_mode(self, mode):
        settings = self.recorder.settings
        area = settings.capture_region
        if mode == "region" and not region_is_available(area):
            area = default_capture_region(int(self.winId()))
        return replace(settings, recording_mode=mode, capture_region=area)

    def save_capture_selection(self, settings):
        self.recorder.settings = settings
        try:
            self.recording_preferences.save(settings)
        except OSError as error:
            self.recording_status.set_message(str(error))
            logger.warning(str(error))
        self.update_region_controls()
        self.update_ready_overlay()

    def update_region_controls(self):
        settings = self.recorder.settings
        ordinary = settings.recording_mode == "region"
        self.region_controls.setVisible(ordinary)
        if ordinary and region_is_available(settings.capture_region):
            area = settings.capture_region
            self.region_details.setText(f"Область: {area.width} × {area.height} пикс.")
            self.region_details.setToolTip(f"Координаты: {area.x}, {area.y}")
        else:
            self.region_details.setText("Сохранённая область недоступна" if settings.capture_region else "Область не выбрана")
            self.region_details.setToolTip("")
        self.update_region_outline()

    def update_region_outline(self):
        settings = self.recorder.settings
        area = settings.capture_region
        if settings.recording_mode != "region" or not region_is_available(area):
            self.close_region_outline()
            return
        if self.region_outline is not None and not self.region_outline.contains_region(area):
            self.close_region_outline()
        if self.region_outline is None:
            if not self.isVisible():
                return
            self.region_outline = RegionOutline(area)
            self.region_outline.resized_region.connect(self.resize_recording_region)
            self.region_outline.show()
        elif self.region_outline.area != area and self.region_outline.drag is None:
            self.region_outline.set_region(area)

    def close_region_outline(self):
        if self.region_outline is not None:
            self.region_outline.hide()
            self.region_outline.deleteLater()
            self.region_outline = None

    def select_recording_region(self, start_after_selection=False):
        if self.recorder.active or self.region_selector is not None or self.region_start_timer.isActive():
            return
        self.region_selection_state = self.windowState()
        self.start_after_region_selection = start_after_selection
        self.region_selector = ScreenRegionSelector(self)
        self.region_selector.selected.connect(self.finish_region_selection)
        self.recorder.hide_overlay()
        self.hide()
        self.region_selector.open()

    def finish_region_selection(self, region):
        selector = self.region_selector
        self.region_selector = None
        selector.deleteLater()
        if region is not None:
            self.save_capture_selection(replace(self.recorder.settings, capture_region=region))
        if region is not None and self.start_after_region_selection:
            self.prepare_region_capture(self.region_selection_state)
        else:
            self.setWindowState(self.region_selection_state)
            self.show()
        self.update_recording_controls()
        self.update_ready_overlay()

    def prepare_region_capture(self, previous_state):
        self.region_restore_state = None if previous_state & Qt.WindowMinimized else previous_state
        self.recorder.hide_overlay()
        self.region_start_timer.start(150)
        self.showMinimized()

    def start_region_capture(self):
        area = self.recorder.settings.capture_region
        if not region_is_available(area):
            self.recording_status.set_message("Выбранная область недоступна. Выберите её заново.")
            self.restore_region_window()
            self.update_region_controls()
            self.update_recording_controls()
            return
        self.recorder.start()
        if not self.recorder.active:
            self.restore_region_window()
        self.update_recording_controls()

    def resize_recording_region(self, area):
        settings = self.recorder.settings
        if (
            settings.recording_mode == "region" and self.region_selector is None
            and self.recording_settings_dialog is None and region_is_available(area)
            and (not self.recorder.active or self.recorder.update_capture_region(area))
        ):
            self.save_capture_selection(replace(self.recorder.settings, capture_region=area))
        elif self.region_outline is not None:
            self.region_outline.set_region(settings.capture_region)

    def update_ready_overlay(self):
        if self.recorder is None or self.recorder.active:
            return
        settings = self.recorder.settings
        ready = settings.recording_mode == "game" or region_is_available(settings.capture_region)
        if (
            ready and self.isVisible() and not self.close_after_recording
            and self.region_selector is None and not self.region_start_timer.isActive()
            and self.recording_settings_dialog is None and self.recording_hotkey
        ):
            self.recorder.show_ready()
        else:
            self.recorder.hide_overlay()

    def showEvent(self, event):
        super().showEvent(event)
        if self.recorder is not None:
            self.update_region_outline()
        self.update_ready_overlay()

    def restore_region_window(self):
        if self.region_restore_state is not None:
            state = self.region_restore_state
            self.region_restore_state = None
            if not self.close_after_recording:
                self.setWindowState(state)
                self.show()

    def toggle_recording_pause(self):
        if not self.close_after_recording and self.recording_settings_dialog is None and self.region_selector is None:
            self.recorder.toggle_pause()
            self.update_recording_controls()

    def on_recording_status(self, message):
        self.recording_status.set_message(message)
        self.update_recording_controls()

    def update_recording_controls(self):
        active = self.recorder.active
        stopping = active and self.recorder.stopping
        paused = active and self.recorder.paused
        recording = active and not stopping and not paused and self.recorder.fps_sample is not None
        if paused:
            state = "Пауза"
        elif self.recorder.pausing:
            state = "Пауза…"
        elif stopping:
            state = "Сохранение"
        elif recording:
            state = "● REC"
        elif active:
            state = "Подготовка"
        else:
            state = "Ожидание"
        self.capture_state.setText(state)
        self.capture_illustration.set_recording(recording)
        if paused:
            action = "Завершить запись"
        else:
            action = "Остановить запись" if active else "Начать запись"
        self.recording_button.setText(action)
        self.recording_button.setEnabled(not stopping)
        self.pause_button.setText("Продолжить" if paused else "Пауза")
        self.pause_button.setEnabled(active and not stopping)
        idle = not active and self.region_selector is None and not self.region_start_timer.isActive()
        self.recording_settings_button.setEnabled(idle)
        for button in self.recording_modes.buttons():
            button.setEnabled(idle)
        self.region_button.setEnabled(idle)
        for widget in (self.capture_state, self.recording_button):
            if widget.property("recording") != recording:
                widget.setProperty("recording", recording)
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def on_recording_finished(self):
        self.restore_region_window()
        self.update_recording_controls()
        self.update_ready_overlay()
        if self.close_after_recording:
            QTimer.singleShot(0, self.close)

    def nativeEvent(self, event_type, message):
        if self.recording_hotkey:
            key = self.recording_hotkey.pressed(event_type, message)
            if key == VK_F12:
                QTimer.singleShot(0, self.toggle_recording)
            elif key == VK_F9:
                QTimer.singleShot(0, self.toggle_recording_pause)
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):
        self.region_start_timer.stop()
        if self.recorder and self.recorder.active:
            self.close_after_recording = True
            self.recording_button.setEnabled(False)
            self.recorder.stop()
            event.ignore()
            return
        if self.recorder is not None:
            self.recorder.hide_overlay()
        self.close_region_outline()
        super().closeEvent(event)
    
    def load_video(self):
        """Загружает видео файл"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Открыть видео", 
            "", 
            "Видео файлы (*.mp4);;Все файлы (*.*)"
        )
        
        if file_path:
            try:
                info = self.processor.load_video_info(file_path)
                self.current_video_path = file_path
                
                duration = self.processor.format_time(info["duration"])
                zero = self.processor.format_time(0)
                self.video_path_label.set_file(Path(file_path))
                self.duration_label.setText(duration)
                self.resolution_label.setText(f"{info['width']} × {info['height']}")
                self.fps_label.setText(f"{info['fps']:.2f} FPS")
                self.codec_label.setText(info["codec"].upper())
                self.size_label.setText(f"{info['file_size']:.2f} МБ")

                max_time_ms = int(info["duration"] * 1000)
                with QSignalBlocker(self.timeline_slider), QSignalBlocker(self.start_time_edit):
                    self.timeline_slider.setMaximum(max_time_ms)
                    self.timeline_slider.setValue(0)
                    self.start_time_edit.setText("00:00:00")
                self.timeline_slider.setEnabled(max_time_ms > 0)
                self.time_label.setText(f"{zero} / {duration}")
                self.end_time_edit.setText(duration)
                
                self.frame_label.clear_frame()
                self.update_frame_preview(0)
                
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить видео:\n{str(e)}")
    
    def on_slider_moved(self, value):
        """Обновляет время при движении слайдера"""
        if self.current_video_path:
            duration = self.processor.get_duration()
            current_time = value / 1000
            self.update_frame_preview(current_time)
            self.time_label.setText(
                f"{self.processor.format_time(current_time)} / "
                f"{self.processor.format_time(duration)}"
            )
    
    def on_start_time_changed(self, value):
        """Обновляет предпросмотр при изменении времени начала"""
        if self.current_video_path:
            start_time = self.parse_time_text(value)
            if start_time >= 0:
                self.update_frame_preview(start_time)
    
    def parse_time_text(self, text: str) -> float:
        """Парсит строку времени в секунды, возвращает -1 при ошибке"""
        seconds = self.processor.parse_time(text)
        normalized = text.strip()
        if seconds == 0:
            if normalized not in ("0", "00", "000", "0:00", "00:00", "0:00:00", "00:00:00"):
                return -1.0
        if not normalized:
            return -1.0
        return seconds
    
    def update_frame_preview(self, timestamp):
        """Обновляет предпросмотр кадра"""
        if self.current_video_path:
            frame = self.processor.get_frame(self.current_video_path, timestamp)
            if frame is not None:
                height, width = frame.shape[:2]
                image = QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888)
                self.frame_label.set_frame(image)
    
    def trim_video(self):
        """Обрезает видео"""
        if not self.current_video_path:
            QMessageBox.warning(self, "Ошибка", "Сначала загрузите видео!")
            return
        
        start_time = self.parse_time_text(self.start_time_edit.text())
        end_time = self.parse_time_text(self.end_time_edit.text())
        
        if start_time < 0 or end_time < 0:
            QMessageBox.warning(self, "Ошибка", "Неверный формат времени. Используйте HH:MM:SS")
            return
        
        if start_time >= end_time:
            QMessageBox.warning(self, "Ошибка", "Время начала должно быть меньше времени конца!")
            return
        
        # Генерируем путь выходного файла
        input_path = Path(self.current_video_path)
        output_path = input_path.parent / f"trimmed_{input_path.stem}.mp4"
        
        # Создаем поток для обрезки
        self.trim_thread = VideoTrimThread(
            self.processor,
            self.current_video_path,
            str(output_path),
            start_time,
            end_time
        )
        
        self.trim_thread.finished.connect(self.on_trim_finished)
        
        self.progress_bar.setVisible(True)
        
        self.trim_thread.start()
    
    def on_trim_finished(self, success, message):
        """Callback при завершении обрезки"""
        self.progress_bar.setVisible(False)
        
        start_time = self.parse_time_text(self.start_time_edit.text())
        end_time = self.parse_time_text(self.end_time_edit.text())
        
        input_path = Path(self.current_video_path)
        output_path = input_path.parent / f"trimmed_{input_path.stem}.mp4"
        
        # Записываем операцию в историю
        history.add_operation(
            input_file=str(input_path),
            output_file=str(output_path),
            start_time=start_time,
            end_time=end_time,
            success=success,
            error_message=None if success else message
        )
        
        # Логируем операцию
        if success:
            logger.info(f"Видео успешно обрезано: {output_path}")
            QMessageBox.information(self, "Успех", message)
        else:
            logger.error(f"Ошибка при обрезке видео: {message}")
            QMessageBox.critical(self, "Ошибка при обрезке", message)


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(APP_ICON)))
    editor = VideoEditor()
    editor.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
