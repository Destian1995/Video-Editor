"""Compose a webcam stream locally with the OpenCV Zoo PP-HumanSeg model."""

from pathlib import Path
from socket import socket
import sys

import cv2
import numpy as np
from PIL import Image, ImageOps

from webcam_capture import SEGMENTED_HEIGHT as HEIGHT, SEGMENTED_WIDTH as WIDTH

MODEL_PATH = Path(__file__).with_name("models") / "pphumanseg.onnx"


class BackgroundReplacement:
    def __init__(self, path):
        self.model = cv2.dnn.readNetFromONNX(np.fromfile(MODEL_PATH, dtype=np.uint8))
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(image, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            self.background = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        self.previous_mask = None

    def apply(self, frame):
        blob = cv2.dnn.blobFromImage(
            frame, 2 / 255, (192, 192), (127.5, 127.5, 127.5), swapRB=True,
        )
        self.model.setInput(blob)
        mask = self.model.forward()[0, 1]
        if self.previous_mask is not None:
            mask = cv2.addWeighted(mask, 0.8, self.previous_mask, 0.2, 0)
        self.previous_mask = mask
        alpha = cv2.resize(mask, (WIDTH, HEIGHT), interpolation=cv2.INTER_LINEAR)
        alpha = np.clip((alpha - 0.35) / 0.35, 0, 1)
        return cv2.blendLinear(frame, self.background, alpha, 1 - alpha)


def stream_replaced_background(path):
    cv2.setNumThreads(2)
    replacement = BackgroundReplacement(path)
    frame_size = WIDTH * HEIGHT * 3
    with socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(10)
        print(server.getsockname()[1], flush=True)
        connection, _ = server.accept()
    try:
        with connection:
            connection.settimeout(5)
            while len(data := sys.stdin.buffer.read(frame_size)) == frame_size:
                frame = np.frombuffer(data, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
                connection.sendall(replacement.apply(frame))
    except (BrokenPipeError, ConnectionResetError):
        pass


if __name__ == "__main__":
    stream_replaced_background(sys.argv[1])
