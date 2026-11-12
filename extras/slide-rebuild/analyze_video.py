"""Find when things change on screen in a finished video (animation builds, slide changes).

    .venv/bin/python tools/analyze_video.py <video> <out.json>

Decodes at 10 fps, 160x90 grey, and reports:
  events   moments where the picture changes (start, end, size of change)
  cuts     big changes (slide changes)
"""
import json
import subprocess
import sys

import numpy as np

W, H, FPS = 160, 90, 10


def frames(path):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS},scale={W}:{H},format=gray",
           "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = W * H
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).astype(np.float32)


def main(src, out):
    prev = None
    diffs = []
    for f in frames(src):
        if prev is not None:
            d = np.abs(f - prev)
            diffs.append((float(d.mean()), float((d > 12).mean())))  # mean change, share of pixels changed
        prev = f
    diffs = np.array(diffs)
    t = (np.arange(len(diffs)) + 1) / FPS
    moving = diffs[:, 1] > 0.002
    events = []
    i = 0
    while i < len(moving):
        if moving[i]:
            j = i
            while j + 1 < len(moving) and (moving[j + 1] or (j + 2 < len(moving) and moving[j + 2])):
                j += 1
            area = float(diffs[i:j + 1, 1].max())
            events.append({"start": round(t[i] - 1 / FPS, 2), "end": round(t[j], 2), "area": round(area, 4),
                           "kind": "cut" if area > 0.35 else "build"})
            i = j + 1
        else:
            i += 1
    json.dump({"duration": round(len(diffs) / FPS, 2), "events": events}, open(out, "w"), indent=1)
    for e in events:
        print("%7.2f-%7.2f  %-5s area=%.3f" % (e["start"], e["end"], e["kind"], e["area"]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
