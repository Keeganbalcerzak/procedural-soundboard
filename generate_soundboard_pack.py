from __future__ import annotations

import base64
import csv
import json
import math
import random
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path


SR = 44_100
ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "clips"
MANIFEST_CSV = ROOT / "soundboard_manifest.csv"
MANIFEST_JSON = ROOT / "soundboard_manifest.json"
CLIPS_MD = ROOT / "CLIPS.md"  # generated clip table; README.md is hand-written
RNG = random.Random(1337)


@dataclass(frozen=True)
class Clip:
    filename: str
    title: str
    category: str
    notes: str
    duration: float


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def write_wav(path: Path, samples: list[float], sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = max((abs(x) for x in samples), default=0.0)
    if peak > 0:
        samples = [x * min(0.96 / peak, 1.0) for x in samples]

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(
            b"".join(struct.pack("<h", int(clamp(x) * 32767)) for x in samples)
        )


def read_wav(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        sr = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if width != 2:
        raise ValueError(f"Expected 16-bit WAV for {path}, got {width * 8}-bit")

    ints = struct.unpack("<" + "h" * (len(frames) // 2), frames)
    samples: list[float] = []
    for index in range(0, len(ints), channels):
        frame = ints[index : index + channels]
        samples.append(sum(frame) / (32767.0 * len(frame)))
    return samples, sr


def trim_and_normalize(samples: list[float], threshold: float = 0.012) -> list[float]:
    if not samples:
        return samples

    start = 0
    while start < len(samples) and abs(samples[start]) < threshold:
        start += 1

    end = len(samples)
    while end > start and abs(samples[end - 1]) < threshold:
        end -= 1

    pad = int(0.045 * SR)
    start = max(0, start - pad)
    end = min(len(samples), end + pad)
    trimmed = samples[start:end] or samples
    return normalize(fade(trimmed, 0.015, 0.06), 0.9)


def normalize(samples: list[float], peak_target: float = 0.92) -> list[float]:
    peak = max((abs(x) for x in samples), default=0.0)
    if peak == 0:
        return samples
    gain = peak_target / peak
    return [clamp(x * gain) for x in samples]


def silence(duration: float) -> list[float]:
    return [0.0] * int(duration * SR)


def fade(samples: list[float], attack: float = 0.01, release: float = 0.04) -> list[float]:
    output = samples[:]
    attack_n = min(len(output), int(attack * SR))
    release_n = min(len(output), int(release * SR))

    for i in range(attack_n):
        output[i] *= i / max(1, attack_n)
    for i in range(release_n):
        output[-1 - i] *= i / max(1, release_n)
    return output


def tone(
    freq: float,
    duration: float,
    amp: float = 0.5,
    shape: str = "sine",
    vibrato: float = 0.0,
    vibrato_rate: float = 5.0,
) -> list[float]:
    samples: list[float] = []
    phase = 0.0
    for n in range(int(duration * SR)):
        t = n / SR
        f = freq + math.sin(2 * math.pi * vibrato_rate * t) * vibrato
        phase += 2 * math.pi * f / SR
        raw = math.sin(phase)
        if shape == "square":
            raw = 1.0 if raw >= 0 else -1.0
        elif shape == "saw":
            raw = 2.0 * ((phase / (2 * math.pi)) % 1.0) - 1.0
        samples.append(raw * amp)
    return fade(samples)


def sweep(
    start_freq: float,
    end_freq: float,
    duration: float,
    amp: float = 0.5,
    shape: str = "sine",
) -> list[float]:
    samples: list[float] = []
    phase = 0.0
    total = max(1, int(duration * SR))
    for n in range(total):
        progress = n / total
        freq = start_freq + (end_freq - start_freq) * progress
        phase += 2 * math.pi * freq / SR
        raw = math.sin(phase)
        if shape == "square":
            raw = 1.0 if raw >= 0 else -1.0
        elif shape == "saw":
            raw = 2.0 * ((phase / (2 * math.pi)) % 1.0) - 1.0
        samples.append(raw * amp)
    return fade(samples)


def noise(duration: float, amp: float = 0.4) -> list[float]:
    return [RNG.uniform(-amp, amp) for _ in range(int(duration * SR))]


def decay(samples: list[float], seconds: float = 0.55) -> list[float]:
    output: list[float] = []
    for n, value in enumerate(samples):
        output.append(value * math.exp(-(n / SR) / seconds))
    return output


def mix(*tracks: list[float]) -> list[float]:
    length = max((len(track) for track in tracks), default=0)
    output = [0.0] * length
    for track in tracks:
        for index, value in enumerate(track):
            output[index] += value
    return normalize(output, 0.92)


def overlay(base: list[float], extra: list[float], offset_seconds: float) -> list[float]:
    offset = int(offset_seconds * SR)
    length = max(len(base), offset + len(extra))
    output = base[:] + [0.0] * (length - len(base))
    for index, value in enumerate(extra):
        output[offset + index] += value
    return output


def cat(*segments: list[float]) -> list[float]:
    output: list[float] = []
    for segment in segments:
        output.extend(segment)
    return output


def chord(freqs: list[float], duration: float, amp: float = 0.4) -> list[float]:
    return mix(*[tone(freq, duration, amp / max(1, len(freqs))) for freq in freqs])


def staccato(freqs: list[float], note_duration: float, gap: float = 0.035, amp: float = 0.55) -> list[float]:
    parts: list[list[float]] = []
    for freq in freqs:
        parts.append(tone(freq, note_duration, amp))
        parts.append(silence(gap))
    return cat(*parts)


def make_sfx() -> dict[str, list[float]]:
    boom_low = decay(sweep(115, 36, 0.72, 0.9), 0.28)
    boom_noise = decay(noise(0.72, 0.22), 0.18)

    bonk = mix(
        decay(tone(430, 0.55, 0.55), 0.12),
        decay(tone(690, 0.52, 0.33), 0.15),
        decay(tone(1180, 0.42, 0.18), 0.08),
        decay(noise(0.18, 0.3), 0.035),
    )

    record = mix(
        sweep(1200, 160, 0.82, 0.42, "saw"),
        decay(noise(0.82, 0.38), 0.35),
    )

    glitches: list[float] = []
    for _ in range(21):
        dur = RNG.uniform(0.015, 0.055)
        if RNG.random() < 0.45:
            glitches.extend(noise(dur, RNG.uniform(0.22, 0.55)))
        else:
            glitches.extend(tone(RNG.choice([180, 260, 520, 740, 1200, 1800]), dur, 0.45, "square"))
        glitches.extend(silence(RNG.uniform(0.004, 0.025)))

    dialup: list[float] = []
    for freq, dur in [(920, 0.08), (1210, 0.07), (480, 0.08), (1750, 0.06), (620, 0.1)]:
        dialup.extend(tone(freq, dur, 0.5, "square"))
        dialup.extend(noise(0.035, 0.28))
    dialup.extend(sweep(2200, 900, 0.22, 0.42, "saw"))

    sfx = {
        "wrong_buzzer.wav": cat(
            tone(165, 0.18, 0.75, "square"),
            silence(0.06),
            tone(155, 0.28, 0.75, "square"),
        ),
        "sad_tromboneish.wav": staccato([392, 370, 349, 294], 0.22, 0.025, 0.52),
        "tiny_violinish.wav": sweep(920, 760, 0.95, 0.55, "sine"),
        "dramatic_boom.wav": mix(boom_low, boom_noise),
        "metal_bonk.wav": bonk,
        "clown_horn.wav": cat(
            sweep(520, 280, 0.23, 0.65, "square"),
            silence(0.04),
            sweep(280, 560, 0.24, 0.65, "square"),
        ),
        "record_scratchish.wav": record,
        "glitch_burst.wav": glitches,
        "fake_ping.wav": cat(chord([980, 1320], 0.16, 0.68), silence(0.05), tone(1560, 0.11, 0.42)),
        "fake_disconnect.wav": staccato([880, 660, 440], 0.12, 0.055, 0.5),
        "microwave_done.wav": staccato([1040, 1040, 1040], 0.12, 0.12, 0.48),
        "suspense_sting.wav": cat(
            chord([622, 659, 698], 0.42, 0.35),
            silence(0.03),
            chord([92, 185, 740], 0.32, 0.62),
        ),
        "cartoon_slip.wav": cat(sweep(420, 1300, 0.28, 0.5), sweep(1300, 300, 0.36, 0.55)),
        "victory_fanfare.wav": staccato([523, 659, 784, 1046], 0.12, 0.025, 0.48),
        "fail_fanfare.wav": staccato([392, 370, 330, 262], 0.16, 0.03, 0.5),
        "airhorn_short.wav": mix(
            tone(230, 0.78, 0.42, "saw", vibrato=22, vibrato_rate=7),
            tone(345, 0.78, 0.3, "square", vibrato=30, vibrato_rate=7),
        ),
        "mini_dialup.wav": dialup,
        "panic_clicks.wav": cat(*[
            cat(noise(RNG.uniform(0.008, 0.018), RNG.uniform(0.25, 0.55)), silence(RNG.uniform(0.018, 0.045)))
            for _ in range(18)
        ]),
        "error_stack.wav": staccato([330, 330, 277, 220], 0.1, 0.045, 0.52),
        "uh_oh_chime.wav": staccato([660, 622, 554], 0.15, 0.035, 0.48),
    }
    return {name: normalize(fade(samples, 0.01, 0.05), 0.9) for name, samples in sfx.items()}


def run_powershell(script: str) -> None:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def synthesize_tts(path: Path, text: str, voice: str, rate: int = 0) -> None:
    escaped_path = str(path).replace("'", "''")
    escaped_text = text.replace("'", "''")
    escaped_voice = voice.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Volume = 100
$synth.Rate = {rate}
try {{ $synth.SelectVoice('{escaped_voice}') }} catch {{ }}
$synth.SetOutputToWaveFile('{escaped_path}')
$synth.Speak('{escaped_text}')
$synth.Dispose()
"""
    run_powershell(script)


def make_tts_clips() -> list[tuple[str, str, str, str, int]]:
    return [
        ("absolutely_not.wav", "Absolutely not.", "Microsoft Zira Desktop", "Hard denial button.", 1),
        ("skill_issue.wav", "Skill issue.", "Microsoft David Desktop", "Small poke for failed plays.", 1),
        ("bro_is_lost.wav", "Bro is lost.", "Microsoft Mark", "For confusing callouts.", 0),
        ("delete_that.wav", "Delete that immediately.", "Microsoft Zira Desktop", "For cursed sentences.", 1),
        ("evidence_folder.wav", "That is going in the evidence folder.", "Microsoft David Desktop", "For suspicious moments.", 0),
        ("pause.wav", "Pause.", "Microsoft Mark", "Tiny interrupt.", -1),
        ("yikes_department.wav", "This came from the yikes department.", "Microsoft Zira Desktop", "Dry commentary.", 1),
        ("chat_is_this_real.wav", "Chat, is this real?", "Microsoft David Desktop", "Streamer-style disbelief.", 1),
        ("i_have_questions.wav", "I have several questions.", "Microsoft Mark", "For baffling choices.", 0),
        ("reported_for_vibes.wav", "Reported for suspicious vibes.", "Microsoft Zira Desktop", "Harmless fake report.", 1),
        ("that_was_illegal.wav", "That was illegal.", "Microsoft David Desktop", "For unfair plays.", 1),
        ("factory_reset_sentence.wav", "Please factory reset that sentence.", "Microsoft Mark", "For verbal disasters.", 1),
        ("uninstall_choices.wav", "Uninstall those life choices.", "Microsoft Zira Desktop", "Roast button.", 1),
        ("the_audacity.wav", "The audacity is remarkable.", "Microsoft David Desktop", "Overdramatic reaction.", 0),
        ("mic_check_nope.wav", "Mic check. Nope.", "Microsoft Mark", "For audio chaos.", 0),
        ("you_tried.wav", "You tried.", "Microsoft Zira Desktop", "Gentle fail sting.", 0),
        ("sir_this_is_discord.wav", "Sir, this is Discord.", "Microsoft David Desktop", "For too-serious rants.", 1),
        ("caught_in_4k.wav", "Caught in four K.", "Microsoft Mark", "For instant evidence.", 1),
        ("straight_to_timeout.wav", "Straight to timeout.", "Microsoft Zira Desktop", "Mock moderation.", 1),
        ("negative_charisma.wav", "Negative charisma detected.", "Microsoft David Desktop", "Low-social-stat gag.", 1),
    ]


def duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    clips: list[Clip] = []

    for filename, samples in make_sfx().items():
        path = OUT_DIR / filename
        write_wav(path, samples)
        clips.append(
            Clip(
                filename=filename,
                title=filename.removesuffix(".wav").replace("_", " ").title(),
                category="SFX",
                notes="Original procedural sound effect.",
                duration=duration_seconds(path),
            )
        )

    for filename, text, voice, notes, rate in make_tts_clips():
        path = OUT_DIR / filename
        synthesize_tts(path, text, voice, rate)
        samples, sr = read_wav(path)
        if sr != SR:
            # Keep the built-in voice sample rate if it differs; most soundboards accept it.
            trimmed = trim_and_normalize(samples)
            write_wav(path, trimmed, sr)
        else:
            write_wav(path, trim_and_normalize(samples), SR)
        clips.append(
            Clip(
                filename=filename,
                title=text,
                category="Voice",
                notes=notes,
                duration=duration_seconds(path),
            )
        )

    clips.sort(key=lambda clip: (clip.category, clip.filename))

    with MANIFEST_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["filename", "title", "category", "duration", "notes"])
        writer.writeheader()
        for clip in clips:
            writer.writerow(
                {
                    "filename": clip.filename,
                    "title": clip.title,
                    "category": clip.category,
                    "duration": f"{clip.duration:.2f}",
                    "notes": clip.notes,
                }
            )

    MANIFEST_JSON.write_text(
        json.dumps([clip.__dict__ for clip in clips], indent=2),
        encoding="utf-8",
    )

    CLIPS_MD.write_text(
        "# Discord Soundboard Clip Pack\n\n"
        "Original, royalty-free WAV clips generated locally for Discord soundboard use.\n\n"
        f"- Clips: {len(clips)}\n"
        "- Format: mono WAV\n"
        "- Suggested use: keep each clip under 2 seconds in your soundboard UI and avoid spamming voice chat.\n\n"
        "## Files\n\n"
        "| File | Type | Length | Notes |\n"
        "| --- | --- | ---: | --- |\n"
        + "\n".join(
            f"| `clips/{clip.filename}` | {clip.category} | {clip.duration:.2f}s | {clip.notes} |"
            for clip in clips
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Generated {len(clips)} clips in {OUT_DIR}")
    print(f"Wrote {MANIFEST_CSV.name}, {MANIFEST_JSON.name}, and {CLIPS_MD.name}")


if __name__ == "__main__":
    main()
