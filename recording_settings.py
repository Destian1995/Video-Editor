"""Параметры записи и диалог их редактирования."""

from dataclasses import dataclass, replace
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Optional

from PyQt5.QtCore import QSettings, QStandardPaths, Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from editor_ui import WebcamBorderPreview
from recording_audio import (
    MicrophoneTest, SOURCES, device_name, list_audio_devices, microphone_meter_level,
)
from screen_region import CaptureRegion, RECORDING_MODES
from webcam_capture import (
    DEFAULT_WEBCAM_BORDER_COLOR, DEFAULT_WEBCAM_BORDER_STYLE, DEFAULT_WEBCAM_POSITION, DEFAULT_WEBCAM_SIZE,
    WEBCAM_BORDER_STYLES, WEBCAM_POSITIONS, WEBCAM_SIZES, webcam_border_color, webcam_border_layers,
    webcam_border_style, webcam_devices, webcam_position, webcam_size,
)
from webcam_preview import WebcamPreviewDialog


MIN_MIC_GAIN = -12
MAX_MIC_GAIN = 30
WEBCAM_UNAVAILABLE = " (недоступна)"


def format_gain(gain_db):
    return f"{gain_db:+d} дБ" if gain_db else "0 дБ"


def default_recording_directory():
    return Path(QStandardPaths.writableLocation(QStandardPaths.MoviesLocation)) / "VideoEditor"


@dataclass(frozen=True)
class RecordingSettings:
    directory: Path
    game_enabled: bool = True
    game_device: str = ""
    microphone_enabled: bool = True
    microphone_device: str = ""
    microphone_gain_db: int = 0
    webcam_enabled: bool = False
    webcam_device: str = ""
    webcam_name: str = ""
    webcam_position: str = DEFAULT_WEBCAM_POSITION
    webcam_border_style: str = DEFAULT_WEBCAM_BORDER_STYLE
    webcam_border_color: str = DEFAULT_WEBCAM_BORDER_COLOR
    webcam_size: str = DEFAULT_WEBCAM_SIZE
    recording_mode: str = "game"
    capture_region: Optional[CaptureRegion] = None
    webcam_background: str = ""

    def audio_selections(self):
        return {
            source: getattr(self, f"{source}_device")
            for source in SOURCES if getattr(self, f"{source}_enabled")
        }


class RecordingPreferences:
    def __init__(self, storage=None):
        self.storage = storage if storage is not None else QSettings(
            QSettings.IniFormat, QSettings.UserScope, "Video Editor", "Video Editor"
        )

    def load(self):
        store = self.storage
        try:
            gain = int(store.value("recording/microphone_gain_db", 0))
        except (TypeError, ValueError):
            gain = 0
        mode = store.value("recording/mode", "game", type=str)
        return RecordingSettings(
            Path(store.value("recording/directory", str(default_recording_directory()), type=str)),
            game_enabled=store.value("recording/game_enabled", True, type=bool),
            game_device=store.value("recording/game_device", "", type=str),
            microphone_enabled=store.value("recording/microphone_enabled", True, type=bool),
            microphone_device=store.value("recording/microphone_device", "", type=str),
            microphone_gain_db=min(MAX_MIC_GAIN, max(MIN_MIC_GAIN, gain)),
            webcam_enabled=store.value("recording/webcam_enabled", False, type=bool),
            webcam_device=store.value("recording/webcam_device", "", type=str),
            webcam_name=store.value("recording/webcam_name", "", type=str),
            webcam_position=store.value("recording/webcam_position", DEFAULT_WEBCAM_POSITION, type=str),
            webcam_border_style=webcam_border_style(
                store.value("recording/webcam_border_style", DEFAULT_WEBCAM_BORDER_STYLE, type=str)
            ),
            webcam_border_color=webcam_border_color(
                store.value("recording/webcam_border_color", DEFAULT_WEBCAM_BORDER_COLOR, type=str)
            ),
            webcam_size=webcam_size(store.value("recording/webcam_size", DEFAULT_WEBCAM_SIZE, type=str)),
            recording_mode=mode if mode in RECORDING_MODES else "game",
            capture_region=CaptureRegion.parse(store.value("recording/region", "", type=str)),
            webcam_background=store.value("recording/webcam_background", "", type=str),
        )

    def save(self, settings):
        store = self.storage
        store.setValue("recording/directory", str(settings.directory))
        store.setValue("recording/game_enabled", settings.game_enabled)
        store.setValue("recording/game_device", settings.game_device)
        store.setValue("recording/microphone_enabled", settings.microphone_enabled)
        store.setValue("recording/microphone_device", settings.microphone_device)
        store.setValue("recording/microphone_gain_db", settings.microphone_gain_db)
        store.setValue("recording/webcam_enabled", settings.webcam_enabled)
        store.setValue("recording/webcam_device", settings.webcam_device)
        store.setValue("recording/webcam_name", settings.webcam_name)
        store.setValue("recording/webcam_position", settings.webcam_position)
        store.setValue("recording/webcam_border_style", settings.webcam_border_style)
        store.setValue("recording/webcam_border_color", settings.webcam_border_color)
        store.setValue("recording/webcam_size", settings.webcam_size)
        store.setValue("recording/webcam_background", settings.webcam_background)
        store.setValue("recording/mode", settings.recording_mode)
        store.setValue("recording/region", settings.capture_region.serialize() if settings.capture_region else "")
        store.sync()
        if store.status() != QSettings.NoError:
            raise OSError("Не удалось записать файл настроек.")


class RecordingSettingsDialog(QDialog):
    def __init__(self, preferences, settings, parent):
        super().__init__(parent)
        self.preferences = preferences
        self.result_settings = settings
        self.mic_test = None
        self.pending_result = None
        self.mic_sample_peak = 0
        self.mic_result_peak = None
        self.setWindowTitle("Настройки записи")
        self.setMinimumWidth(520)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(22, 16, 22, 20)
        shell.setSpacing(14)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.tabBar().setDrawBase(False)
        shell.addWidget(tabs)
        audio_tab = QWidget()
        layout = QVBoxLayout(audio_tab)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(9)
        tabs.addTab(audio_tab, "Запись и звук")
        folder_label = QLabel("Папка сохранения MP4")
        folder_label.setObjectName("sectionTitle")
        layout.addWidget(folder_label)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(str(settings.directory))
        self.folder.setAccessibleName(folder_label.text())
        folder_label.setBuddy(self.folder)
        folder_row.addWidget(self.folder, 1)
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self.browse)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        try:
            devices, defaults = list_audio_devices()
        except (ImportError, OSError, ValueError):
            devices, defaults = {}, {}
            warning = QLabel("Не удалось прочитать список аудиоустройств Windows.")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        self.audio_controls = {}
        for source, title in SOURCES.items():
            layout.addSpacing(8)
            enabled = QCheckBox(f"Записывать {title.lower()}")
            enabled.setChecked(getattr(settings, f"{source}_enabled"))
            layout.addWidget(enabled)
            device = QComboBox()
            device.setAccessibleName(f"{title} — устройство")
            default = defaults.get(source)
            default_text = f"По умолчанию — {device_name(default)}" if default else "По умолчанию"
            device.addItem(default_text, "")
            for name in devices.get(source, {}):
                device.addItem(name, name)
            selected = getattr(settings, f"{source}_device")
            if selected and device.findData(selected) < 0:
                device.addItem(f"{selected} (недоступно)", selected)
            device.setCurrentIndex(device.findData(selected))
            device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            device.setMinimumContentsLength(18)
            device.setEnabled(enabled.isChecked())
            enabled.toggled.connect(device.setEnabled)
            layout.addWidget(device)
            self.audio_controls[source] = (enabled, device)

        self.mic_device = self.audio_controls["microphone"][1]
        self.mic_device.currentIndexChanged.connect(self.reset_microphone_test)

        gain_row = QHBoxLayout()
        gain_label = QLabel("Усиление микрофона")
        self.mic_gain = QSlider(Qt.Horizontal)
        self.mic_gain.setAccessibleName(gain_label.text())
        self.mic_gain.setRange(MIN_MIC_GAIN, MAX_MIC_GAIN)
        self.mic_gain.setPageStep(3)
        self.mic_gain.setValue(settings.microphone_gain_db)
        gain_label.setBuddy(self.mic_gain)
        self.mic_gain_value = QLabel(format_gain(self.mic_gain.value()))
        self.mic_gain_value.setObjectName("timecode")
        self.mic_gain_value.setMinimumWidth(58)
        self.mic_gain_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gain_row.addWidget(gain_label)
        gain_row.addWidget(self.mic_gain, 1)
        gain_row.addWidget(self.mic_gain_value)
        layout.addLayout(gain_row)

        test_row = QHBoxLayout()
        self.mic_test_button = QPushButton("Проверить микрофон")
        self.mic_test_button.clicked.connect(self.toggle_microphone_test)
        test_row.addWidget(self.mic_test_button)
        self.mic_level = QProgressBar()
        self.mic_level.setObjectName("micLevel")
        self.mic_level.setAccessibleName("Уровень сигнала микрофона")
        self.mic_level.setTextVisible(False)
        self.mic_level.setValue(0)
        test_row.addWidget(self.mic_level, 1)
        layout.addLayout(test_row)
        self.mic_status = QLabel("Микрофон не проверен.")
        self.mic_status.setObjectName("muted")
        self.mic_status.setWordWrap(True)
        layout.addWidget(self.mic_status)
        self.mic_gain.valueChanged.connect(self.update_microphone_gain)

        note = QLabel(
            "Звук игры берётся с выбранных динамиков или наушников. "
            "Если включены оба источника, они записываются в общую дорожку AAC."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

        camera_tab = self.create_webcam_tab(settings)
        tabs.addTab(camera_tab, "Веб-камера")
        tabs.currentChanged.connect(self.load_webcams)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Save).setProperty("primary", True)
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        shell.addWidget(buttons)

    def create_webcam_tab(self, settings):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)

        self.webcam_enabled = QCheckBox("Добавлять веб-камеру в запись")
        self.webcam_enabled.setChecked(settings.webcam_enabled)
        layout.addWidget(self.webcam_enabled)
        device_row = QHBoxLayout()
        self.webcam_device = QComboBox()
        self.webcam_device.setAccessibleName("Веб-камера")
        self.webcam_device.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.webcam_device.setMinimumContentsLength(18)
        if settings.webcam_device:
            self.webcam_device.addItem(settings.webcam_name or "Выбранная камера", settings.webcam_device)
        self.webcam_list_loaded = False
        device_row.addWidget(self.webcam_device, 1)
        refresh = QPushButton("Обновить")
        refresh.clicked.connect(self.refresh_webcams)
        device_row.addWidget(refresh)
        layout.addLayout(device_row)
        self.webcam_status = QLabel()
        self.webcam_status.setObjectName("muted")
        self.webcam_status.setWordWrap(True)
        self.webcam_status.hide()
        layout.addWidget(self.webcam_status)

        title = QLabel("Положение в кадре")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        placement = QFrame()
        placement.setObjectName("webcamPlacement")
        placement.setFixedSize(300, 156)
        grid = QGridLayout(placement)
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(6)
        self.webcam_positions = QButtonGroup(placement)
        self.webcam_position_label = QLabel()
        self.webcam_position_label.setObjectName("muted")
        # The center is deliberately left free for the recorded desktop.
        arrows = ("↖", "↑", "↗", "←", "→", "↙", "↓", "↘")
        cells = (0, 1, 2, 3, 5, 6, 7, 8)
        selected = settings.webcam_position
        if selected not in WEBCAM_POSITIONS:
            selected = DEFAULT_WEBCAM_POSITION
        for (position, (name, _, _)), arrow, cell in zip(WEBCAM_POSITIONS.items(), arrows, cells):
            button = QPushButton(arrow)
            button.setObjectName("webcamPosition")
            button.setProperty("position", position)
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.setCheckable(True)
            button.setChecked(position == selected)
            self.webcam_positions.addButton(button)
            row, column = divmod(cell, 3)
            grid.addWidget(button, row, column)
        self.webcam_position_label.setText(webcam_position(selected)[0])
        self.webcam_positions.buttonClicked.connect(self.on_webcam_position_changed)
        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        preview_row.addWidget(placement)
        sample = QVBoxLayout()
        sample.addStretch()
        preview_label = QLabel("Предпросмотр рамки")
        preview_label.setObjectName("muted")
        sample.addWidget(preview_label)
        self.border_preview = WebcamBorderPreview()
        sample.addWidget(self.border_preview)
        sample.addStretch()
        preview_row.addLayout(sample)
        preview_row.addStretch()
        layout.addLayout(preview_row)
        layout.addWidget(self.webcam_position_label)

        border_controls = QWidget()
        appearance = QVBoxLayout(border_controls)
        appearance.setContentsMargins(0, 0, 0, 0)
        size_row = QHBoxLayout()
        size_label = QLabel("Размер веб-камеры")
        self.webcam_size = QComboBox()
        self.webcam_size.setAccessibleName(size_label.text())
        size_label.setBuddy(self.webcam_size)
        for size, (name, _) in WEBCAM_SIZES.items():
            self.webcam_size.addItem(name, size)
        self.webcam_size.setCurrentIndex(self.webcam_size.findData(webcam_size(settings.webcam_size)))
        size_row.addWidget(size_label)
        size_row.addWidget(self.webcam_size, 1)
        appearance.addLayout(size_row)

        border_row = QHBoxLayout()
        border_label = QLabel("Стиль рамки")
        self.border_style = QComboBox()
        self.border_style.setAccessibleName(border_label.text())
        border_label.setBuddy(self.border_style)
        for style, (name, _) in WEBCAM_BORDER_STYLES.items():
            self.border_style.addItem(name, style)
        style = webcam_border_style(settings.webcam_border_style)
        self.border_style.setCurrentIndex(self.border_style.findData(style))
        self.border_style.currentIndexChanged.connect(self.update_webcam_border)
        self.border_color = webcam_border_color(settings.webcam_border_color)
        self.border_color_button = QPushButton()
        self.border_color_button.setAccessibleName("Цвет рамки")
        self.border_color_button.clicked.connect(self.choose_webcam_border_color)
        border_row.addWidget(border_label)
        border_row.addWidget(self.border_style, 1)
        border_row.addWidget(self.border_color_button)
        appearance.addLayout(border_row)

        background_row = QHBoxLayout()
        background_label = QLabel("Фон веб-камеры")
        self.webcam_background = QLineEdit(settings.webcam_background)
        self.webcam_background.setReadOnly(True)
        self.webcam_background.setPlaceholderText("Исходный фон")
        self.webcam_background.textChanged.connect(self.webcam_background.setToolTip)
        self.webcam_background.setToolTip(settings.webcam_background)
        background_label.setBuddy(self.webcam_background)
        choose_background = QPushButton("Картинка…")
        choose_background.clicked.connect(self.choose_webcam_background)
        clear_background = QPushButton("Сбросить")
        clear_background.clicked.connect(self.webcam_background.clear)
        background_row.addWidget(background_label)
        background_row.addWidget(self.webcam_background, 1)
        background_row.addWidget(choose_background)
        background_row.addWidget(clear_background)
        appearance.addLayout(background_row)

        clear_background.setEnabled(bool(settings.webcam_background))
        self.webcam_background.textChanged.connect(lambda path: clear_background.setEnabled(bool(path)))

        layout.addWidget(border_controls)
        self.update_webcam_border()
        test_camera = QPushButton("Проверить веб-камеру")
        test_camera.clicked.connect(self.test_webcam)
        layout.addWidget(test_camera, alignment=Qt.AlignLeft)

        self.webcam_enabled.toggled.connect(placement.setEnabled)
        self.webcam_enabled.toggled.connect(self.webcam_device.setEnabled)
        self.webcam_enabled.toggled.connect(border_controls.setEnabled)
        placement.setEnabled(settings.webcam_enabled)
        self.webcam_device.setEnabled(settings.webcam_enabled)
        border_controls.setEnabled(settings.webcam_enabled)
        layout.addStretch()
        return tab

    def test_webcam(self):
        device = self.webcam_device.currentData()
        if not device:
            self.webcam_status.setText("Выберите веб-камеру для проверки.")
            self.webcam_status.show()
            return
        background = self.webcam_background.text()
        if background and not Path(background).is_file():
            self.webcam_status.setText("Картинка фона недоступна. Выберите другой файл или сбросьте фон.")
            self.webcam_status.show()
            return
        self.webcam_status.hide()
        preview = WebcamPreviewDialog(
            device, self.border_style.currentData(), self.border_color, self,
            size=self.webcam_size.currentData(), background=background,
        )
        preview.exec_()
        preview.deleteLater()

    def choose_webcam_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Картинка для фона веб-камеры", self.webcam_background.text(),
            "Изображения (*.png *.jpg *.jpeg)",
        )
        if path:
            self.webcam_background.setText(path)

    def choose_webcam_border_color(self):
        color = QColorDialog.getColor(QColor(self.border_color), self, "Цвет рамки веб-камеры")
        if color.isValid():
            self.border_color = color.name()
            self.update_webcam_border()

    def update_webcam_border(self):
        layers = webcam_border_layers(self.border_style.currentData(), self.border_color)
        self.border_preview.set_layers(layers)
        swatch = QPixmap(14, 14)
        swatch.fill(QColor(self.border_color))
        self.border_color_button.setIcon(QIcon(swatch))
        self.border_color_button.setText(f"Цвет {self.border_color.upper()}")
        self.border_color_button.setEnabled(bool(layers))

    def on_webcam_position_changed(self, button):
        self.webcam_position_label.setText(button.accessibleName())

    def load_webcams(self, index):
        if index == 1 and not self.webcam_list_loaded:
            self.refresh_webcams()

    def selected_webcam_name(self):
        name = self.webcam_device.currentText()
        return name[:-len(WEBCAM_UNAVAILABLE)] if name.endswith(WEBCAM_UNAVAILABLE) else name

    def refresh_webcams(self):
        selected = self.webcam_device.currentData()
        selected_name = self.selected_webcam_name()
        try:
            cameras = webcam_devices()
            status = "" if cameras else "Камеры не найдены. Подключите камеру и нажмите «Обновить»."
        except (OSError, TimeoutExpired):
            cameras = {}
            status = "Не удалось получить список веб-камер."
        self.webcam_device.clear()
        for identifier, name in cameras.items():
            self.webcam_device.addItem(name, identifier)
        if selected and selected not in cameras:
            self.webcam_device.addItem(selected_name + WEBCAM_UNAVAILABLE, selected)
        selected_index = self.webcam_device.findData(selected)
        if selected_index >= 0:
            self.webcam_device.setCurrentIndex(selected_index)
        self.webcam_status.setText(status)
        self.webcam_status.setVisible(bool(status))
        self.webcam_list_loaded = True

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Папка для записей", self.folder.text())
        if path:
            self.folder.setText(path)

    def toggle_microphone_test(self):
        if self.mic_test is not None:
            self.mic_test.stop()
            self.mic_test_button.setEnabled(False)
            return
        self.mic_result_peak = None
        self.update_microphone_peak(0)
        self.mic_status.setText("Подключение к микрофону…")
        self.mic_status.setToolTip("")
        self.mic_test_button.setText("Остановить проверку")
        self.mic_test = MicrophoneTest(self.mic_device.currentData(), self)
        self.mic_test.started_listening.connect(self.show_microphone_prompt)
        self.mic_test.peak_changed.connect(self.update_microphone_peak)
        self.mic_test.finished.connect(self.finish_microphone_test)
        self.mic_test.start()

    def show_microphone_prompt(self):
        if self.mic_test is not None and not self.mic_test.stop_event.is_set():
            self.mic_status.setText("Говорите в микрофон несколько секунд.")

    def update_microphone_peak(self, peak):
        self.mic_sample_peak = peak
        self.mic_level.setValue(microphone_meter_level(peak, self.mic_gain.value()))

    def update_microphone_gain(self, gain):
        self.mic_gain_value.setText(format_gain(gain))
        if self.mic_result_peak is not None:
            self.show_microphone_result(self.mic_result_peak)
        else:
            self.update_microphone_peak(self.mic_sample_peak)

    def show_microphone_result(self, peak):
        self.mic_result_peak = peak
        self.update_microphone_peak(peak)
        level = self.mic_level.value()
        if level >= 100:
            self.mic_status.setText("Уровень сигнала слишком высокий. Уменьшите усиление.")
        elif level >= 20:
            self.mic_status.setText("Сигнал микрофона обнаружен.")
        else:
            self.mic_status.setText("Уровень сигнала слишком низкий.")

    def reset_microphone_test(self):
        if self.mic_test is not None:
            self.mic_test.stop()
            self.mic_test_button.setEnabled(False)
        self.mic_result_peak = None
        self.update_microphone_peak(0)
        self.mic_status.setText("Микрофон не проверен.")
        self.mic_status.setToolTip("")

    def finish_microphone_test(self):
        test = self.mic_test
        self.mic_test = None
        test.deleteLater()
        if self.pending_result is not None:
            result = self.pending_result
            self.pending_result = None
            super().done(result)
            return
        self.mic_test_button.setText("Проверить микрофон")
        self.mic_test_button.setEnabled(True)
        if test.selection != self.mic_device.currentData():
            self.reset_microphone_test()
        elif test.error:
            self.mic_status.setText(test.error)
            self.mic_status.setToolTip(test.error_details)
            self.update_microphone_peak(0)
        elif test.stop_event.is_set() and microphone_meter_level(test.peak, self.mic_gain.value()) < 20:
            self.mic_status.setText("Проверка остановлена.")
            self.update_microphone_peak(0)
        else:
            self.show_microphone_result(test.peak)

    def accept(self):
        try:
            directory = Path(self.folder.text().strip()).expanduser()
            if not directory.is_absolute():
                raise ValueError("Укажите полный путь к папке.")
            directory.mkdir(parents=True, exist_ok=True)
            options = {}
            for source, (enabled, device) in self.audio_controls.items():
                options[f"{source}_enabled"] = enabled.isChecked()
                options[f"{source}_device"] = device.currentData()
            webcam_device = self.webcam_device.currentData() or ""
            if self.webcam_enabled.isChecked() and not webcam_device:
                raise ValueError("Выберите веб-камеру или отключите её запись.")
            background = self.webcam_background.text()
            if self.webcam_enabled.isChecked() and background and not Path(background).is_file():
                raise ValueError("Картинка фона недоступна. Выберите другой файл или сбросьте фон.")
            webcam_name = self.selected_webcam_name()
            position = self.webcam_positions.checkedButton().property("position")
            settings = replace(
                self.result_settings, directory=directory, microphone_gain_db=self.mic_gain.value(),
                webcam_enabled=self.webcam_enabled.isChecked(),
                webcam_device=webcam_device, webcam_name=webcam_name, webcam_position=position,
                webcam_border_style=self.border_style.currentData(), webcam_border_color=self.border_color,
                webcam_size=self.webcam_size.currentData(),
                webcam_background=background,
                **options,
            )
            self.preferences.save(settings)
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Настройки записи", str(error))
            return
        self.result_settings = settings
        self.done(QDialog.Accepted)

    def reject(self):
        self.done(QDialog.Rejected)

    def done(self, result):
        if self.mic_test is not None:
            if self.pending_result is None:
                self.pending_result = result
                self.mic_test.stop()
                self.setEnabled(False)
        else:
            super().done(result)
