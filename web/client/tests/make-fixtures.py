"""Trois sons synthétiques pour la recette locale, sans données client."""
from pathlib import Path
import math
import struct
import wave

root = Path(__file__).parent / "_fixtures"
root.mkdir(exist_ok=True)
for name, frequency, rate, channels in [
    ("première.wav", 440, 16000, 1),
    ("suite.wav", 880, 44100, 2),
    ("autre.wav", 220, 48000, 1),
]:
    with wave.open(str(root / name), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * frequency * index / rate))) * channels
            for index in range(rate)
        ))
