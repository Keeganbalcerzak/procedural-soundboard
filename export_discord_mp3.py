from __future__ import annotations

import csv
import json
import struct
import sys
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / ".vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

import lameenc


WAV_DIR = ROOT / "clips"
MP3_DIR = ROOT / "discord-ready-mp3"
MANIFEST_CSV = ROOT / "discord_ready_manifest.csv"
MANIFEST_JSON = ROOT / "discord_ready_manifest.json"


def read_wav_pcm(path: Path) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError(f"{path.name} is {sample_width * 8}-bit; expected 16-bit WAV")

    if channels == 1:
        return frames, sample_rate, channels

    values = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    mono = []
    for index in range(0, len(values), channels):
        mono.append(int(sum(values[index : index + channels]) / channels))
    return struct.pack("<" + "h" * len(mono), *mono), sample_rate, 1


def encode_mp3(wav_path: Path, mp3_path: Path) -> None:
    pcm, sample_rate, channels = read_wav_pcm(wav_path)
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(64)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(channels)
    encoder.set_quality(2)

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_data = encoder.encode(pcm) + encoder.flush()
    mp3_path.write_bytes(mp3_data)


def duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def main() -> None:
    rows = []
    for wav_path in sorted(WAV_DIR.glob("*.wav")):
        mp3_path = MP3_DIR / f"{wav_path.stem}.mp3"
        encode_mp3(wav_path, mp3_path)
        rows.append(
            {
                "filename": mp3_path.name,
                "source_wav": wav_path.name,
                "duration": f"{duration_seconds(wav_path):.2f}",
                "size_kb": f"{mp3_path.stat().st_size / 1024:.1f}",
            }
        )

    with MANIFEST_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["filename", "source_wav", "duration", "size_kb"])
        writer.writeheader()
        writer.writerows(rows)

    MANIFEST_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Exported {len(rows)} MP3 files to {MP3_DIR}")


if __name__ == "__main__":
    main()
