"""Word-timed transcripts with whisper.cpp (runs locally; nothing leaves the Mac).

    words = transcribe("vo.mp3")     # [{"w": "welcome", "t": 0.21, "e": 0.55}, ...]
Results are cached next to the job (`<audio>.words.json`) so re-runs are free.
"""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .config import CFG

MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en-q5_1.bin"


def norm(s):
    return re.sub(r"[^a-z0-9']", "", s.lower().replace("’", "'"))


def ensure_model():
    m = Path(CFG.whisper_model)
    if not m.exists() or m.stat().st_size < 10_000_000:
        m.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-4", "-sSL", "-o", str(m), MODEL_URL], check=True)
    return m


def transcribe(audio, cache_dir=None):
    audio = Path(audio)
    cache = Path(cache_dir or audio.parent) / (audio.name + ".words.json")
    if cache.exists() and cache.stat().st_mtime >= audio.stat().st_mtime:
        return json.loads(cache.read_text())
    model = ensure_model()
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
                       check=True)
        base = os.path.join(td, "out")
        subprocess.run([CFG.whisper_bin, "-m", str(model), "-f", wav, "-ojf", "-of", base, "-ml", "1", "-sow",
                        "-t", str(max(2, (os.cpu_count() or 4) - 1))], check=True, capture_output=True)
        data = json.load(open(base + ".json"))
    words = []
    for s in data["transcription"]:
        t = s["text"].strip()
        if not t:
            continue
        for part in t.split():  # a "token" can still hold two words ("one-time" etc.)
            n = norm(part)
            if n:
                words.append({"w": n, "raw": part, "t": s["offsets"]["from"] / 1000, "e": s["offsets"]["to"] / 1000})
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(words))
    return words
