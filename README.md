# Discord Soundboard Pack Generator

Generates an original, royalty-free soundboard pack for Discord and exports it as Discord-ready MP3s. Nothing is sampled from existing media:

- **20 sound effects** (airhorn, bonk, sad trombone-ish, glitch burst, fake ping, ...) synthesized from scratch in pure Python: oscillators, noise, envelopes and pitch sweeps.
- **20 voice lines** ("Skill issue.", "Sir, this is Discord.", ...) spoken by the built-in Windows voices through `System.Speech`, then trimmed and normalized.

## Requirements

- **Windows** for the voice lines. `generate_soundboard_pack.py` calls PowerShell and `System.Speech` (the Microsoft Zira, David and Mark voices). The sound effects themselves are plain Python.
- Python 3.10+
- [`lameenc`](https://pypi.org/project/lameenc/) for MP3 encoding:
  ```bash
  pip install -r requirements.txt
  ```
  (`export_discord_mp3.py` also checks a local `.vendor/` folder first, so a vendored copy of `lameenc` works too.)

## Usage

```bash
# 1. Synthesize all 40 clips as 16-bit mono WAVs into clips/
python generate_soundboard_pack.py

# 2. Encode every WAV in clips/ to MP3 in discord-ready-mp3/
python export_discord_mp3.py
```

| Script | Output |
| --- | --- |
| `generate_soundboard_pack.py` | `clips/*.wav`, `soundboard_manifest.csv/.json`, `CLIPS.md` (generated table of every clip) |
| `export_discord_mp3.py` | `discord-ready-mp3/*.mp3`, `discord_ready_manifest.csv/.json` (duration and size per file) |

The generator uses a fixed random seed, so the sound effects come out the same on every run. The audio folders are build output and aren't committed. The manifests and [`CLIPS.md`](CLIPS.md) show what one run produces.

## Discord limits

Discord soundboard sounds must be **MP3s under 512 KB and no longer than 5 seconds**. This pack stays well inside both limits:

- Every clip is between 0.3 and 2 seconds long (sound effects are built to fixed short lengths, and voice lines are silence-trimmed).
- MP3s are mono at 64 kbps, which comes to about 3 to 16 KB per clip.

The export script records each file's duration and size in `discord_ready_manifest.csv`, so you can check them before you upload. It doesn't reject files, though. If you add your own longer clips, check them against the limits yourself.

Uploading is manual. See [DISCORD_UPLOAD_STEPS.md](DISCORD_UPLOAD_STEPS.md). You need the **Create Expressions** permission in the server. `discord-upload-queue/` is just a hand-picked copy of 8 of the MP3s to upload first.
