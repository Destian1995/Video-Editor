"""Предпросмотр источников, шкала монтажа и экспорт выбранных фрагментов."""

import math
from pathlib import Path
import re

from PyQt5.QtCore import Qt, QSignalBlocker
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider, QVBoxLayout,
)

from editor_ui import FileLabel, FramePreview, card, label, style_title_bar
from logger import logger
from video_montage import EXPORT_PROFILES, Clip, MontageExport, insert_clip
from video_processor import VideoProcessor


def format_timestamp(milliseconds):
    seconds, remainder = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{remainder:03d}"


def parse_timestamp(text):
    text = text.strip().replace(",", ".")
    if not re.fullmatch(r"(?:[0-9]+:){0,2}[0-9]+(?:\.[0-9]{1,3})?", text):
        raise ValueError("Укажите время в секундах или в формате ЧЧ:ММ:СС.мс.")
    whole, _, fraction = text.partition(".")
    seconds = 0
    for part in whole.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds * 1000 + int(fraction.ljust(3, "0"))


def format_file_size(size):
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.2f} ГБ"
    return f"{size / 1_000_000:.1f} МБ"


class MontageDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Монтаж видео")
        self.setMinimumSize(730, 600)
        self.resize(990, 675)
        self.processor = VideoProcessor()
        self.sources = {}
        self.timeline = []
        self.export_job = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        source, source_layout = card()
        montage, montage_layout = card()
        source_layout.setSpacing(8)
        montage_layout.setSpacing(8)
        layout.addWidget(source, 5)
        layout.addWidget(montage, 6)

        source_layout.addWidget(label("Исходное видео", "sectionTitle"))
        self.source_picker = QComboBox()
        self.source_picker.setAccessibleName("Исходное видео")
        self.source_picker.setPlaceholderText("Выберите видео")
        self.source_picker.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source_picker.currentIndexChanged.connect(self.select_source)
        self.add_button = QPushButton("Добавить видео…")
        self.add_button.clicked.connect(self.choose_sources)
        source_bar = QHBoxLayout()
        source_bar.addWidget(self.source_picker, 1)
        source_bar.addWidget(self.add_button)
        source_layout.addLayout(source_bar)

        self.preview = FramePreview()
        source_layout.addWidget(self.preview, 1)
        self.source_time = label("—", "timecode")
        source_layout.addWidget(self.source_time)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setAccessibleName("Позиция в исходном видео")
        self.seek.setRange(0, 0)
        self.seek.valueChanged.connect(self.show_source_frame)
        source_layout.addWidget(self.seek)

        range_layout = QHBoxLayout()
        self.range_start = self.add_time_field(range_layout, "Начало фрагмента")
        self.range_end = self.add_time_field(range_layout, "Конец фрагмента")
        source_layout.addLayout(range_layout)
        marks = QHBoxLayout()
        for title, field in (("Отметить начало", self.range_start), ("Отметить конец", self.range_end)):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, target=field: target.setText(format_timestamp(self.seek.value())))
            marks.addWidget(button)
        self.mark_controls = marks
        source_layout.addLayout(marks)

        montage_layout.addWidget(label("Шкала монтажа", "sectionTitle"))
        self.clips = QListWidget()
        self.clips.setAccessibleName("Фрагменты монтажа")
        self.clips.setAlternatingRowColors(True)
        self.clips.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.clips.currentRowChanged.connect(self.select_clip)
        self.clips.itemDoubleClicked.connect(self.open_clip)
        montage_layout.addWidget(self.clips, 1)

        order = QHBoxLayout()
        self.up_button = QPushButton("↑ Выше")
        self.down_button = QPushButton("↓ Ниже")
        self.remove_button = QPushButton("Удалить")
        self.up_button.clicked.connect(lambda: self.move_clip(-1))
        self.down_button.clicked.connect(lambda: self.move_clip(1))
        self.remove_button.clicked.connect(self.remove_clip)
        for button in (self.up_button, self.down_button, self.remove_button):
            order.addWidget(button)
        montage_layout.addLayout(order)

        placement = QHBoxLayout()
        self.position = self.add_time_field(placement, "Время вставки в монтаже")
        self.position.setToolTip("Введите время или выберите фрагмент, перед которым нужно вставить видео.")
        self.end_button = QPushButton("В конец")
        self.end_button.clicked.connect(self.select_end)
        placement.addWidget(self.end_button, alignment=Qt.AlignBottom)
        montage_layout.addLayout(placement)
        self.insert_button = QPushButton("Вставить фрагмент")
        self.insert_button.clicked.connect(self.add_clip)
        montage_layout.addWidget(self.insert_button)
        self.total = FileLabel("value")
        montage_layout.addWidget(self.total)

        profiles = QHBoxLayout()
        profile_caption = label("Сжатие MP4", "muted")
        self.profile_picker = QComboBox()
        profile_caption.setBuddy(self.profile_picker)
        self.profile_picker.setAccessibleName("Сжатие MP4")
        for profile in EXPORT_PROFILES:
            self.profile_picker.addItem(profile.name, profile)
        self.profile_picker.currentIndexChanged.connect(self.update_export_estimate)
        profiles.addWidget(profile_caption)
        profiles.addWidget(self.profile_picker, 1)
        montage_layout.addLayout(profiles)
        self.estimate = FileLabel()
        montage_layout.addWidget(self.estimate)

        self.export_button = QPushButton("Сохранить монтаж…")
        self.export_button.setProperty("primary", True)
        self.export_button.clicked.connect(self.export_montage)
        montage_layout.addWidget(self.export_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Экспорт монтажа")
        self.progress.hide()
        montage_layout.addWidget(self.progress)
        self.progress_status = FileLabel("value")
        self.progress_time = FileLabel()
        for status in (self.progress_status, self.progress_time):
            status.hide()
            montage_layout.addWidget(status)
        self.refresh_timeline()
        self.select_source()
        style_title_bar(self)

    def add_time_field(self, layout, title):
        group = QVBoxLayout()
        group.setSpacing(4)
        field = QLineEdit(format_timestamp(0))
        field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        field.setToolTip("ЧЧ:ММ:СС.мс или секунды")
        field.setAccessibleName(title)
        caption = label(title, "muted")
        caption.setBuddy(field)
        group.addWidget(caption)
        group.addWidget(field)
        layout.addLayout(group, 1)
        return field

    def choose_sources(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Добавить видео", "",
            "Видео (*.mp4 *.mkv *.mov *.webm *.avi *.m4v *.mts *.m2ts);;Все файлы (*.*)",
        )
        self.add_sources(paths)

    def add_sources(self, paths):
        errors = []
        first = None
        with QSignalBlocker(self.source_picker):
            for path in paths:
                path = Path(path).resolve()
                if path not in self.sources:
                    try:
                        info = self.processor.load_video_info(str(path))
                        raw_duration = info["video_duration"]
                        duration = float(raw_duration) if raw_duration not in (None, "N/A") else info["duration"]
                        if not math.isfinite(duration) or not 0 < duration < 2_147_483:
                            raise ValueError("Не удалось определить длительность видео.")
                        info["duration_ms"] = max(1, round(duration * 1000))
                    except (OSError, ValueError, RuntimeError) as error:
                        errors.append(f"{path.name} — {error}")
                        continue
                    self.sources[path] = info
                    self.source_picker.addItem(path.name, path)
                    self.source_picker.setItemData(self.source_picker.count() - 1, str(path), Qt.ToolTipRole)
                if first is None:
                    first = path
        if first is not None:
            index = self.source_picker.findData(first)
            if index == self.source_picker.currentIndex():
                self.select_source()
            else:
                self.source_picker.setCurrentIndex(index)
        if errors:
            QMessageBox.warning(self, "Не удалось загрузить видео", "\n".join(errors))

    def select_source(self):
        path = self.source_picker.currentData()
        duration = self.sources[path]["duration_ms"] if path else 0
        with QSignalBlocker(self.seek):
            self.seek.setRange(0, duration)
            self.seek.setValue(0)
        self.seek.setEnabled(bool(path))
        self.range_start.setEnabled(bool(path))
        self.range_end.setEnabled(bool(path))
        self.insert_button.setEnabled(bool(path))
        for index in range(self.mark_controls.count()):
            self.mark_controls.itemAt(index).widget().setEnabled(bool(path))
        self.range_start.setText(format_timestamp(0))
        self.range_end.setText(format_timestamp(duration))
        self.preview.clear_frame()
        if path:
            self.show_source_frame(0)

    def show_source_frame(self, position):
        path = self.source_picker.currentData()
        if not path:
            return
        info = self.sources[path]
        duration = info["duration_ms"]
        self.source_time.setText(f"{format_timestamp(position)} / {format_timestamp(duration)}")
        last_frame = max(0, duration / 1000 - 1 / (info["fps"] or 30))
        frame = self.processor.get_frame(str(path), min(position / 1000, last_frame))
        if frame is not None:
            height, width = frame.shape[:2]
            self.preview.set_frame(QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888))

    def refresh_timeline(self, selected=-1):
        with QSignalBlocker(self.clips):
            self.clips.clear()
            time = 0
            for clip in self.timeline:
                end = time + clip.duration
                positions = f"{format_timestamp(time)} – {format_timestamp(end)}"
                item = QListWidgetItem(f"{positions}\n{clip.path.name}")
                item.setToolTip(
                    f"{clip.path}\nФрагмент {format_timestamp(clip.start)} – {format_timestamp(clip.end)}"
                )
                self.clips.addItem(item)
                time = end
            self.clips.setCurrentRow(selected)
        self.total.set_full_text(f"Общая длительность {format_timestamp(time)}")
        self.end_button.setEnabled(bool(self.timeline))
        self.export_button.setEnabled(bool(self.timeline) and self.export_job is None)
        self.update_export_estimate()
        self.select_clip(selected)
        self.select_end()

    def select_clip(self, row):
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < len(self.timeline) - 1)
        self.remove_button.setEnabled(row >= 0)
        if row >= 0:
            self.position.setText(format_timestamp(sum(clip.duration for clip in self.timeline[:row])))

    def select_end(self):
        self.position.setText(format_timestamp(sum(clip.duration for clip in self.timeline)))

    def open_clip(self, item):
        clip = self.timeline[self.clips.row(item)]
        self.source_picker.setCurrentIndex(self.source_picker.findData(clip.path))
        self.range_start.setText(format_timestamp(clip.start))
        self.range_end.setText(format_timestamp(clip.end))
        self.seek.setValue(clip.start)

    def add_clip(self):
        path = self.source_picker.currentData()
        if not path:
            return
        try:
            start = parse_timestamp(self.range_start.text())
            end = parse_timestamp(self.range_end.text())
            if not 0 <= start < end <= self.sources[path]["duration_ms"]:
                raise ValueError("Начало и конец должны образовывать диапазон в пределах исходного видео.")
            clip = Clip(path, start, end)
            selected = insert_clip(self.timeline, clip, parse_timestamp(self.position.text()))
        except ValueError as error:
            QMessageBox.warning(self, "Проверьте время фрагмента", str(error))
            return
        self.refresh_timeline(selected)

    def move_clip(self, direction):
        row = self.clips.currentRow()
        destination = row + direction
        if 0 <= row < len(self.timeline) and 0 <= destination < len(self.timeline):
            self.timeline.insert(destination, self.timeline.pop(row))
            self.refresh_timeline(destination)

    def remove_clip(self):
        row = self.clips.currentRow()
        if row >= 0:
            self.timeline.pop(row)
            self.refresh_timeline(min(row, len(self.timeline) - 1))

    def update_export_estimate(self):
        profile = self.profile_picker.currentData()
        if not self.timeline:
            self.estimate.set_full_text("")
            return
        if not profile.max_video_kbps:
            self.estimate.set_full_text("Размер зависит от сложности кадров.")
            return
        has_audio = any(self.sources[part.path]["has_audio"] for part in self.timeline)
        bitrate = profile.max_video_kbps + (profile.audio_kbps if has_audio else 0)
        size = sum(part.duration for part in self.timeline) * bitrate / 8
        self.estimate.set_full_text(
            f"Оценка размера · до {format_file_size(size)}",
            "Ориентир по предельному битрейту. Итоговый размер зависит от кадров и формата MP4.",
        )

    def export_montage(self):
        if not self.timeline or self.export_job is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить монтаж", str(self.timeline[0].path.with_name("montage.mp4")),
            "Видео MP4 (*.mp4)", options=QFileDialog.DontConfirmOverwrite,
        )
        if not path:
            return
        output = Path(path).resolve()
        if output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")
        if output in self.sources:
            QMessageBox.warning(self, "Сохранение монтажа", "Выберите имя, отличное от исходных файлов.")
            return
        if output.exists() and QMessageBox.question(
            self, "Заменить файл", f"Заменить существующий файл «{output.name}»?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        job = MontageExport(
            tuple(self.timeline), self.sources.copy(), output, self, self.profile_picker.currentData(),
        )
        self.export_job = job
        job.finished.connect(self.export_finished)
        job.progress.connect(self.update_export_progress)
        job.finalizing.connect(self.show_finalizing)
        self.export_button.setEnabled(False)
        self.profile_picker.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.progress_status.set_full_text("Подготовка экспорта…")
        self.progress_status.show()
        self.progress_time.hide()
        job.start()

    def update_export_progress(self, milliseconds, speed):
        duration = self.export_job.duration_ms
        milliseconds = min(milliseconds, duration)
        if milliseconds and duration - milliseconds <= min(250, duration * 0.01):
            self.show_finalizing()
            return
        percent = min(99, int(100 * milliseconds / duration))
        self.progress.setValue(max(percent, self.progress.value()))
        self.progress_status.set_full_text(f"Кодирование · {self.progress.value()}%")
        elapsed = format_timestamp(milliseconds).split(".")[0]
        total = format_timestamp(duration).split(".")[0]
        message = f"{elapsed} / {total}"
        if math.isfinite(speed) and speed > 0 and milliseconds >= 1000:
            remaining = math.ceil((duration - milliseconds) / speed / 1000)
            message += f" · Осталось ≈ {format_timestamp(remaining * 1000).split('.')[0]}"
        self.progress_time.set_full_text(message)
        self.progress_time.show()

    def show_finalizing(self):
        self.progress.setValue(99)
        self.progress_status.set_full_text("Завершение сохранения MP4 · 99%")
        self.progress_time.hide()

    def export_finished(self):
        job = self.export_job
        self.export_job = None
        self.progress_time.hide()
        self.profile_picker.setEnabled(True)
        self.export_button.setEnabled(bool(self.timeline))
        if job.error:
            self.progress.hide()
            self.progress_status.set_full_text("Экспорт завершился ошибкой.")
            logger.error(f"Не удалось экспортировать монтаж: {job.error}")
            QMessageBox.critical(self, "Ошибка экспорта", job.error)
        else:
            self.progress.setValue(100)
            self.progress_status.set_full_text(f"Готово · 100% · {format_file_size(job.size)}", str(job.output))
            QMessageBox.information(self, "Монтаж сохранён", str(job.output))
        job.deleteLater()

    def reject(self):
        if self.export_job is None:
            super().reject()
