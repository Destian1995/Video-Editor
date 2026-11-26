"""Захват звука Windows и сборка дорожки для MP4."""

from contextlib import ExitStack
from dataclasses import dataclass
from math import log10
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event
from time import monotonic, time
from typing import Optional

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


SOURCES = {"game": "Звук игры", "microphone": "Микрофон"}


def device_name(device):
    return device["name"].replace(" [Loopback]", "").strip()


def wasapi_devices(audio, module):
    api = audio.get_host_api_info_by_type(module.paWASAPI)
    devices = {"game": {}, "microphone": {}}
    for index in range(audio.get_device_count()):
        device = audio.get_device_info_by_index(index)
        if device["hostApi"] == api["index"] and device["maxInputChannels"]:
            source = "game" if device["isLoopbackDevice"] else "microphone"
            devices[source].setdefault(device_name(device), device)
    defaults = {"game": None, "microphone": None}
    try:
        defaults["game"] = audio.get_default_wasapi_loopback()
    except (LookupError, OSError):
        pass
    if api["defaultInputDevice"] >= 0:
        defaults["microphone"] = audio.get_device_info_by_index(api["defaultInputDevice"])
    return devices, defaults


def list_audio_devices():
    import pyaudiowpatch

    with pyaudiowpatch.PyAudio() as audio:
        return wasapi_devices(audio, pyaudiowpatch)


def selected_device(devices, defaults, source, selection):
    return devices[source].get(selection) if selection else defaults[source]


def open_input_stream(audio, module, device, callback):
    return audio.open(
        rate=int(device["defaultSampleRate"]), channels=device["maxInputChannels"],
        format=module.paInt16, input=True, input_device_index=device["index"],
        frames_per_buffer=1024, start=False, stream_callback=callback,
    )


def microphone_meter_level(peak, gain_db):
    if not peak:
        return 0
    db = 20 * log10(peak / 32768) + gain_db
    return min(100, max(0, round((db + 60) * (100 / 60))))


class MicrophoneTest(QThread):
    started_listening = pyqtSignal()
    peak_changed = pyqtSignal(int)
    duration = 8

    def __init__(self, selection, parent):
        super().__init__(parent)
        self.selection = selection
        self.stop_event = Event()
        self.sample_peak = 0
        self.peak = 0
        self.error = ""
        self.error_details = ""

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            import pyaudiowpatch as module

            with module.PyAudio() as audio:
                devices, defaults = wasapi_devices(audio, module)
                device = selected_device(devices, defaults, "microphone", self.selection)
                if device is None:
                    self.error = "Выбранный микрофон недоступен."
                    return
                if self.stop_event.is_set():
                    return

                def receive(data, frames, clock, flags):
                    if data and not self.stop_event.is_set():
                        samples = np.frombuffer(data, dtype="<i2")
                        self.sample_peak = max(abs(int(samples.min())), abs(int(samples.max())))
                        self.peak = max(self.sample_peak, self.peak)
                    return None, module.paContinue

                with open_input_stream(audio, module, device, receive) as stream:
                    if self.stop_event.is_set():
                        return
                    stream.start_stream()
                    self.started_listening.emit()
                    deadline = monotonic() + self.duration
                    while not self.stop_event.wait(0.06):
                        if not stream.is_active():
                            self.error = "Микрофон прервал проверку."
                            break
                        self.peak_changed.emit(self.sample_peak)
                        if monotonic() >= deadline:
                            break
        except (ImportError, OSError, ValueError) as error:
            self.error = "Не удалось открыть микрофон. Проверьте устройство и доступ к микрофону в Windows."
            self.error_details = str(error)


@dataclass
class AudioTrack:
    path: Path
    rate: int
    channels: int
    first_sample: Optional[float] = None
    frames: int = 0

    def write(self, file, data, timestamp):
        frame_size = 2 * self.channels
        if self.first_sample is None:
            self.first_sample = timestamp
        gap = round((timestamp - self.first_sample) * self.rate) - self.frames
        # Loopback can pause while the playback device has no active streams.
        # Ignore small callback jitter and preserve longer gaps as silence.
        if gap > self.rate * 0.15:
            silence = bytes(frame_size * self.rate)
            for _ in range(gap // self.rate):
                file.write(silence)
            file.write(silence[:(gap % self.rate) * frame_size])
            self.frames += gap
        elif gap < -self.rate * 0.15:
            data = data[-gap * frame_size:]
        file.write(data)
        self.frames += len(data) // frame_size


class AudioCapture(QThread):
    ready = pyqtSignal(object, object)

    def __init__(self, directory, selections, parent):
        super().__init__(parent)
        self.directory = directory
        self.selections = selections
        self.tracks = {}
        self.errors = {}
        self.stop_event = Event()
        self.buffers = Queue(maxsize=256)
        self.dropped = set()

    def stop(self):
        self.stop_event.set()

    def _callback(self, source, rate, module):
        def receive(data, frames, clock, flags):
            if data and not self.stop_event.is_set():
                if flags & module.paInputOverflow:
                    self.dropped.add(source)
                delay = clock["current_time"] - clock["input_buffer_adc_time"]
                if not frames / rate <= delay < 1:
                    delay = frames / rate
                try:
                    self.buffers.put_nowait((source, data, time() - delay))
                except Full:
                    self.dropped.add(source)
            return None, module.paContinue
        return receive

    def run(self):
        files = {}
        try:
            import pyaudiowpatch as module

            with module.PyAudio() as audio, ExitStack() as tracks, ExitStack() as streams:
                devices, defaults = wasapi_devices(audio, module)
                names = {}
                active_streams = {}
                for source, selection in self.selections.items():
                    if self.stop_event.is_set():
                        break
                    device = selected_device(devices, defaults, source, selection)
                    if device is None:
                        self.errors[source] = "устройство недоступно"
                        continue
                    rate = int(device["defaultSampleRate"])
                    channels = device["maxInputChannels"]
                    track = AudioTrack(self.directory / f"{source}.pcm", rate, channels)
                    try:
                        file = tracks.enter_context(track.path.open("wb"))
                        stream = streams.enter_context(open_input_stream(
                            audio, module, device, self._callback(source, rate, module),
                        ))
                        stream.start_stream()
                    except (OSError, ValueError) as error:
                        self.errors[source] = str(error)
                        continue
                    self.tracks[source] = track
                    files[source] = file
                    active_streams[source] = stream
                    names[source] = device_name(device)

                self.ready.emit(names, self.errors.copy())
                while self.tracks and not self.stop_event.is_set():
                    try:
                        self._write(files, self.buffers.get(timeout=0.1))
                    except Empty:
                        continue
                for source, stream in active_streams.items():
                    if not stream.is_active():
                        self.errors.setdefault(source, "устройство прервало захват")
                streams.close()
                while not self.buffers.empty():
                    self._write(files, self.buffers.get_nowait())
        except (ImportError, OSError, ValueError) as error:
            for source in self.selections:
                self.errors.setdefault(source, str(error))
        for source, track in list(self.tracks.items()):
            if not track.frames:
                self.errors.setdefault(source, "аудиоданные не получены")
                del self.tracks[source]
        for source in self.dropped:
            self.errors.setdefault(source, "часть аудиоданных потеряна")

    def _write(self, files, buffer):
        source, data, timestamp = buffer
        if source in self.tracks:
            self.tracks[source].write(files[source], data, timestamp)


def mux_audio_args(video, output, tracks, video_start, microphone_gain_db=0):
    args = ["-hide_banner", "-nostdin", "-loglevel", "warning", "-n", "-i", str(video)]
    filters = []
    inputs = []
    with_microphone = "microphone" in tracks
    for index, (source, track) in enumerate(tracks.items(), 1):
        args += [
            "-f", "s16le", "-ar", str(track.rate), "-ac", str(track.channels),
            "-i", str(track.path),
        ]
        offset = track.first_sample - video_start
        start = (
            f"atrim=start={-offset:.6f},asetpts=PTS-STARTPTS"
            if offset < 0 else f"adelay={round(offset * 1000)}:all=1"
        )
        channel = f"[audio{index}]"
        stereo = "aformat=channel_layouts=stereo"
        gain = ""
        if source == "microphone":
            if track.channels == 1:
                stereo = "pan=stereo|FL=c0|FR=c0"
            if microphone_gain_db:
                gain = f",volume={microphone_gain_db}dB"
        elif with_microphone:
            # Keep the existing game level in the mix and give the voice its own gain.
            gain = ",volume=0.5"
        filters.append(f"[{index}:a]{start},aresample=48000,{stereo}{gain},apad{channel}")
        inputs.append(channel)
    if len(inputs) > 1:
        filters.append(f"{''.join(inputs)}amix=inputs={len(inputs)}:normalize=0[mix]")
        inputs = ["[mix]"]
    if with_microphone:
        filters.append(f"{inputs[0]}alimiter=limit=0.94:level=false:latency=true[limited]")
        inputs = ["[limited]"]
    return args + [
        "-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", inputs[0],
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", str(output),
    ]
