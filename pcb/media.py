"""Small ffmpeg/ffprobe helpers."""
import re
import subprocess


def duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def decodes_cleanly(path) -> bool:
    """Full decode. ffprobe alone misses damaged files (this matters on Macs that corrupt big files)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    return r.returncode == 0 and not r.stderr.strip()


def silence_ends(path, noise_db=-40, min_len=0.25):
    """Times where a silence ends (speech resumes)."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af", f"silencedetect=n={noise_db}dB:d={min_len}",
                        "-f", "null", "-"], capture_output=True, text=True)
    return [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr)]


def vtt_to_srt(vtt, srt):
    lines = open(vtt, encoding="utf-8-sig").read().splitlines()
    cues, cur = [], None
    for ln in lines:
        if "-->" in ln:
            a, b = [x.strip().split(" ")[0] for x in ln.split("-->")]
            fix = lambda t: (t if t.count(":") == 2 else "00:" + t).replace(".", ",")
            cur = [fix(a), fix(b), []]
            cues.append(cur)
        elif cur is not None and ln.strip():
            cur[2].append(re.sub(r"<[^>]+>", "", ln))
        elif not ln.strip():
            cur = None
    with open(srt, "w", encoding="utf-8") as f:
        for i, (a, b, txt) in enumerate(cues, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (i, a, b, "\n".join(txt)))
    return srt
