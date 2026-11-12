"""Find animation builds in a slide clip and read the text each build adds."""
import json
from difflib import SequenceMatcher
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .config import CFG
from .media import duration

W, H, FPS = 160, 90, 10


def _frames(path):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={FPS},scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    n = W * H
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).astype(np.float32)


def change_events(path):
    """Moments where the picture changes: [{"start", "end", "area"}] (area = share of pixels changed)."""
    prev, diffs = None, []
    for f in _frames(path):
        if prev is not None:
            diffs.append(float((np.abs(f - prev) > 12).mean()))
        prev = f
    t = (np.arange(len(diffs)) + 1) / FPS
    moving = [d > 0.002 for d in diffs]
    ev, i = [], 0
    while i < len(moving):
        if moving[i]:
            j = i
            while j + 1 < len(moving) and (moving[j + 1] or (j + 2 < len(moving) and moving[j + 2])):
                j += 1
            ev.append({"start": round(t[i] - 1 / FPS, 2), "end": round(t[j], 2), "area": round(max(diffs[i:j + 1]), 4)})
            i = j + 1
        else:
            i += 1
    return ev


def builds(path):
    """-> {"duration", "builds": [{"start","end"}], "cut_end"}.
    A short final change (an element blinking out before the clip ends — a Canva export quirk)
    is not a build: the clip is treated as ending just before it."""
    d = duration(path)
    ev = change_events(path)
    cut_end = d
    if ev and ev[-1]["end"] - ev[-1]["start"] <= 0.25:
        cut_end = ev[-1]["start"]
        ev = ev[:-1]
    return {"duration": d, "builds": [{"start": e["start"], "end": e["end"]} for e in ev], "cut_end": cut_end}


def grab(path, t, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(path), "-frames:v", "1", str(out)],
                   check=True)
    return out


def ocr(images):
    """OCR several images in one call -> list of [lines] (each line {"text","x","y","w","h","conf"})."""
    if not images:
        return []
    out = subprocess.run([str(CFG.bin_dir / "ocr"), *map(str, images)], capture_output=True, text=True, check=True).stdout
    by_file = {}
    for ln in out.splitlines():
        d = json.loads(ln)
        by_file[d["file"]] = d.get("lines", [])
    return [by_file.get(str(i), []) for i in images]


def build_texts(path, info, workdir):
    """OCR the frame before the first build and after each build; return per-build added text
    plus the fully built frame's text."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    times = []
    bl = info["builds"]
    times.append(bl[0]["start"] - 0.05 if bl else 0.3)
    for k, b in enumerate(bl):
        nxt = bl[k + 1]["start"] if k + 1 < len(bl) else info["cut_end"]
        times.append(min(b["end"] + 0.25, nxt - 0.05))
    times.append(info["cut_end"] - 0.1)
    imgs = [grab(path, t, workdir / f"{stem}_{i:02d}.png") for i, t in enumerate(times)]
    texts = ocr(imgs)
    added = []
    for k in range(len(bl)):
        # OCR reads the same line slightly differently frame to frame ("Test if" / "Test it"),
        # so a line only counts as new if nothing similar was on screen before the build
        before = [_key(l["text"]) for l in texts[k]]
        new = []
        for l in texts[k + 1]:
            key = _key(l["text"])
            if len(key) > 1 and not any(SequenceMatcher(None, key, b).ratio() >= 0.75 for b in before):
                new.append(l["text"])
        added.append(new)
    return {"before_first": [l["text"] for l in texts[0]], "added": added, "final": texts[-1]}


def _key(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())
