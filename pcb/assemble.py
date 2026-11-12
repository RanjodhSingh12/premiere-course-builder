"""Folder of slide clips + voiceover + storyboard  ->  slides retimed to the voice + a Premiere edit spec.

Expected folder (names are flexible, case-insensitive):
    <folder>/storyboard/*.docx       storyboard (Scene | Script | Words | OST | Notes)
    <folder>/canva/**/*.mp4          slide clips, numbered in play order (1.mp4, 2.mp4, ...)
    <folder>/audio/*.mp3|wav|m4a     voiceover, one or more files, in name order

How it decides timing (no hand-written cues):
  1. Whisper transcribes the voiceover with word timings (local).
  2. Each clip's builds are found (frame differences); macOS Vision reads the text each build adds.
  3. Clips are assigned to storyboard scenes by matching on-screen text to the scene's title + OST.
  4. Each scene starts when the first words of its script are spoken.
  5. Each build is placed where its text (or the closest wording) is spoken.
  6. Clips are cut at their builds; the still stretches are held or shortened so builds land on
     their words. The fully built frame is held to the end of the scene.
"""
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from . import media as M
from . import storyboard as SB
from . import video as V
from .config import CFG
from .transcribe import norm, transcribe

FPS = 30
STOP = set("a an the and or of to for in on at by with from as is are be was it its this that these those your you "
           "we our their they he she his her them can will what which who how into than then so but if not no".split())
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".aif", ".aiff"}


def _natkey(p):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", p.name)]


def find_inputs(folder):
    folder = Path(folder).expanduser()
    files = [p for p in folder.rglob("*") if p.is_file() and not p.name.startswith((".", "._"))]
    sb = [p for p in files if p.suffix.lower() == ".docx" and "storyboard" in str(p).lower()] or \
         [p for p in files if p.suffix.lower() == ".docx"]
    vids = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    # slide clips = the folder holding the most videos (ignores finished renders sitting elsewhere)
    by_dir = {}
    for v in vids:
        by_dir.setdefault(v.parent, []).append(v)
    clips = sorted(max(by_dir.values(), key=len), key=_natkey) if by_dir else []
    audio = sorted([p for p in files if p.suffix.lower() in AUDIO_EXT], key=_natkey)
    return {"folder": str(folder), "storyboard": str(sb[0]) if sb else None,
            "clips": [str(p) for p in clips], "audio": [str(p) for p in audio]}


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_word(t):
    """'24' -> 'twentyfour' so spoken and written numbers match ('twenty-four' -> 'twentyfour' too)."""
    if t.isdigit() and int(t) < 100:
        n = int(t)
        return _ONES[n] if n < 20 else _TENS[n // 10] + (_ONES[n % 10] if n % 10 else "")
    return t


def content_tokens(text):
    text = re.sub(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[\s-]+(one|two|three|four|five|six|seven|eight|nine)\b",
                  r"\1\2", text, flags=re.I)
    return [num_word(t) for t in (norm(w) for w in re.split(r"[\s/\-–—,.;:()]+", text)) if t and t not in STOP and len(t) > 1]


def _stem(t):
    for suf in ("ings", "ing", "ied", "ies", "ed", "es", "s", "ly"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            t = t[: -len(suf)]
            break
    if len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    return t


def _bag(tokens):
    return {_stem(t) for t in tokens}


# ---------- transcript ----------

def build_transcript(audio_files, workdir):
    words, offsets, t0 = [], [], 0.0
    for a in audio_files:
        offsets.append(t0)
        for w in transcribe(a, cache_dir=workdir):
            words.append(dict(w, t=w["t"] + t0, e=w["e"] + t0))
        t0 += M.duration(a) + CFG.audio_gap_seconds
    total = t0 - CFG.audio_gap_seconds
    return words, offsets, total


def find_phrase(words, text, after, before=None, min_score=None):
    """Where is `text` (or most of its content words) spoken, after `after` seconds?
    Candidate windows start ON a matching word and run at most `span` words; the best window has
    the most matching words, then the tightest cluster, then the earliest start.
    Returns (time of the window's first word, score) or (None, best_score)."""
    toks = content_tokens(text)
    if not toks:
        return None, 0.0
    want = _bag(toks)
    if min_score is None:   # short texts must match fully; longer ones need about half their words
        min_score = 0.99 if len(want) <= 2 else 0.4
    span = max(6, 2 * len(toks) + 4)
    stems = [_stem(num_word(w["w"])) for w in words]
    best, best_key = (None, 0.0), None
    for i, w in enumerate(words):
        if w["t"] < after - 0.05 or (before is not None and w["t"] > before):
            continue
        if stems[i] not in want:
            continue
        seen, last = set(), i
        for j in range(i, min(len(words), i + span)):
            if stems[j] in want and stems[j] not in seen:
                seen.add(stems[j])
                last = j
        score = len(seen) / len(want)
        key = (round(score, 3), -(last - i), -i)
        if best_key is None or key > best_key:
            best_key, best = key, (float(w["t"]), score)
    return best if best[1] >= min_score else (None, best[1])


def script_start(words, scene, after):
    """When does this scene's voiceover begin? Match the first sentence of its script, in order."""
    lines = [l for l in scene["script"] if l.strip()]
    if not lines:
        return None
    first = " ".join(lines[0].split()[:8])
    seq = [norm(w) for w in first.split() if norm(w)]
    # exact in-order match of the first 3+ words is the strongest signal
    for n in (5, 4, 3):
        if len(seq) < n:
            continue
        for i in range(len(words) - n + 1):
            if words[i]["t"] >= after - 0.05 and all(words[i + k]["w"] == seq[k] for k in range(n)):
                return words[i]["t"]
    t, _ = find_phrase(words, first, after)
    return t


def snap_to_silence(t, silence_ends, window=1.0):
    cand = [s for s in silence_ends if t - window <= s <= t + 0.3]
    return max(cand) if cand else t


# ---------- clips -> scenes ----------

def assign_clips(clip_texts, scenes):
    """Monotonic assignment (DP) maximizing on-screen-text overlap with each scene's title + OST."""
    sc_bags = [_bag(content_tokens(" ".join([s["title"] or s["name"]] + s["ost"]))) for s in scenes]
    tl_bags = [_bag(content_tokens(s["title"] or s["name"])) for s in scenes]

    def score(ci, sj):
        cb = _bag(content_tokens(" ".join(clip_texts[ci])))
        if not cb:
            return 0.0
        ost = len(cb & sc_bags[sj]) / len(cb)
        title = len(tl_bags[sj] & cb) / max(1, len(tl_bags[sj]))
        return ost + 0.5 * title

    n, m = len(clip_texts), len(scenes)
    NEG = -1e9
    dp = [[NEG] * m for _ in range(n)]
    back = [[0] * m for _ in range(n)]
    for j in range(m):
        dp[0][j] = score(0, j) - 0.3 * j          # prefer starting at the first scene
    for i in range(1, n):
        for j in range(m):
            best, arg = NEG, j
            for k in range(0, j + 1):
                gap_pen = 0.3 * max(0, j - k - 1)   # skipping scenes is allowed but penalised
                v = dp[i - 1][k] - gap_pen
                if v > best:
                    best, arg = v, k
            dp[i][j] = best + score(i, j)
            back[i][j] = arg
    j = max(range(m), key=lambda x: dp[n - 1][x] - 0.3 * (m - 1 - x))
    out = [0] * n
    for i in range(n - 1, -1, -1):
        out[i] = j
        j = back[i][j]
    return out, [round(score(i, out[i]), 2) for i in range(n)]


# ---------- retiming ----------

def retime_clip(src, info, targets, D, out):
    """Cut `src` at its builds and hold/shorten the still parts so build k starts at targets[k]
    (seconds from the clip's start in the output); total length D."""
    bl = info["builds"]
    pieces = []
    if bl:
        starts = [b["start"] for b in bl]
        pieces.append((0, min(starts[0], targets[0]), targets[0]))
        for k in range(len(bl)):
            s_to = starts[k + 1] if k + 1 < len(bl) else info["cut_end"]
            length = (targets[k + 1] if k + 1 < len(targets) else D) - targets[k]
            pieces.append((starts[k], min(s_to, starts[k] + length), length))
    else:
        pieces.append((0, min(info["cut_end"], D), D))
    parts, labels = [], []
    for i, (a, b, L) in enumerate(pieces):
        b = max(b, a + 1 / FPS)
        hold = max(0.0, L - (b - a))
        parts.append(f"[0:v]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS,"
                     f"tpad=stop_mode=clone:stop_duration={hold:.4f}[p{i}]")
        labels.append(f"[p{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0,fps={FPS},trim=duration={D:.4f}[v]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", graph, "-map", "[v]",
                    "-c:v", "libx264", "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p", str(out)], check=True)


# ---------- main ----------

def plan(folder, job_dir=None, log=print):
    inp = find_inputs(folder)
    if not inp["storyboard"] or not inp["clips"] or not inp["audio"]:
        raise ValueError(f"need a storyboard .docx, slide clips and audio in {folder}: found {inp}")
    name = Path(folder).expanduser().name
    job = Path(job_dir or (CFG.jobs_dir / name))
    (job / "work").mkdir(parents=True, exist_ok=True)
    (job / "retimed").mkdir(exist_ok=True)

    sb = SB.read(inp["storyboard"])
    scenes = sb["scenes"]
    log(f"storyboard: {len(scenes)} scenes; clips: {len(inp['clips'])}; audio files: {len(inp['audio'])}")

    words, offsets, vo_end = build_transcript(inp["audio"], job / "work")
    sil = []
    for a, off in zip(inp["audio"], offsets):
        sil += [s + off for s in M.silence_ends(a)]
    log(f"transcript: {len(words)} words, voiceover {vo_end:.1f}s")

    clips = []
    for c in inp["clips"]:
        info = V.builds(c)
        texts = V.build_texts(c, info, job / "work" / "frames")
        clips.append({"src": c, "info": info, "texts": texts})
    log(f"builds found: {sum(len(c['info']['builds']) for c in clips)}")

    final_texts = [[l["text"] for l in c["texts"]["final"]] for c in clips]
    assign, conf = assign_clips(final_texts, scenes)

    # scene start times
    scene_t, after = {}, 0.0
    for j in sorted(set(assign)):
        t = script_start(words, scenes[j], after)
        if t is not None:
            t = snap_to_silence(t, sil)
            scene_t[j] = t
            after = t + 0.5

    # per-build targets (absolute seconds)
    rows, prev_build_t = [], 0.0
    for i, c in enumerate(clips):
        j = assign[i]
        first_of_scene = i == 0 or assign[i - 1] != j
        next_scene = next((scene_t[assign[k]] for k in range(i + 1, len(clips)) if assign[k] != j and assign[k] in scene_t), vo_end)
        lo = scene_t.get(j, prev_build_t) if first_of_scene else prev_build_t
        targets, how = [], []
        cursor = lo
        for k, b in enumerate(c["info"]["builds"]):
            text = " ".join(c["texts"]["added"][k])
            t, score = find_phrase(words, text, cursor, before=next_scene + 1.0)
            if t is None:
                how.append(f"unmatched({score:.2f})")
            else:
                how.append(f"{score:.2f}")
            targets.append(t)
            if t is not None:
                cursor = t + 0.3
        rows.append({"clip": Path(c["src"]).name, "scene": scenes[j]["n"], "scene_title": scenes[j]["title"],
                     "assign_score": conf[i], "first_of_scene": first_of_scene, "targets": targets, "how": how,
                     "texts": c["texts"]["added"]})
        known = [t for t in targets if t is not None]
        if known:
            prev_build_t = max(known)

    # clip start times: a scene's first clip starts when the scene's words start; a follow-on clip
    # starts just before its first build's words
    starts = []
    for i, r in enumerate(rows):
        c = clips[i]
        if i == 0:
            s = 0.0
        elif r["first_of_scene"] and assign[i] in scene_t:
            s = scene_t[assign[i]] - 0.25
        else:
            b1 = r["targets"][0] if r["targets"] else None
            if b1 is None:
                # first build unmatched: find where this slide's whole text is spoken instead
                b1, _ = find_phrase(words, " ".join(final_texts[i]), starts[-1] + 1.0, min_score=0.25)
            lead_in = min(c["info"]["builds"][0]["start"], 0.8) if c["info"]["builds"] else 0.5
            s = (b1 - CFG.lead_seconds - lead_in) if b1 is not None else (starts[-1] + 3.0)
        starts.append(max(s, (starts[-1] + 0.5) if starts else 0.0))
    total = vo_end + CFG.tail_seconds

    out_clips, markers, report = [], [], []
    for i, r in enumerate(rows):
        c = clips[i]
        S = round(starts[i] * FPS) / FPS
        E = round((starts[i + 1] if i + 1 < len(rows) else total) * FPS) / FPS
        D = E - S
        bl = c["info"]["builds"]
        # fill unmatched targets by spacing them evenly between their matched neighbours
        tg = list(r["targets"])
        for k in range(len(tg)):
            if tg[k] is None:
                prev = next((tg[x] for x in range(k - 1, -1, -1) if tg[x] is not None), S + 0.3)
                nxt_i = next((x for x in range(k + 1, len(tg)) if tg[x] is not None), None)
                # trailing unmatched builds share the time left in the clip
                nxt = tg[nxt_i] if nxt_i is not None else max(prev + 0.6, E - 1.0)
                gaps = (nxt_i if nxt_i is not None else len(tg) + 1) - k + 1
                tg[k] = prev + (nxt - prev) / gaps
        local = [t - S - CFG.lead_seconds for t in tg]
        floor = min(bl[0]["start"], 0.8) if bl else 0.0
        for k in range(len(local)):
            anim = bl[k]["end"] - bl[k]["start"] + 0.1
            local[k] = max(local[k], floor)
            floor = local[k] + anim
            local[k] = min(local[k], max(0.0, D - anim))
        out = job / "retimed" / f"{i + 1:02d}_{Path(c['src']).stem}.mp4"
        retime_clip(c["src"], c["info"], local, D, out)
        out_clips.append({"file": str(out), "at": S, "dur": D})
        if r["first_of_scene"]:
            markers.append({"time": S, "name": f"{r['scene']}. {r['scene_title'] or ''}".strip()})
        report.append(dict(r, start=S, end=E, builds_at=[round(float(S + t), 2) for t in local]))
        log(f"clip {r['clip']:>8} -> scene {r['scene']:>2} ({r['assign_score']:.2f})  {S:7.2f}-{E:7.2f}  "
            f"builds {[round(float(S + t), 1) for t in local]}  match {r['how']}")

    spec = {
        "name": sb["title"] or name,
        "output_dir": str(job / "output"),
        "media": [c["file"] for c in out_clips] + inp["audio"],
        "sequence_from": 0,
        "clips": [{"media": i, "in": 0, "out": round(M.duration(c["file"]), 4), "at": c["at"]} for i, c in enumerate(out_clips)],
        "audio": [{"media": len(out_clips) + k, "at": round(off, 3)} for k, off in enumerate(offsets)],
        "markers": markers,
        "export": True,
        "overwrite": True,
    }
    spec["name"] = re.sub(r"\s+", " ", spec["name"]).strip()[:120]
    (job / "edit.json").write_text(json.dumps(spec, indent=2))
    (job / "plan.json").write_text(json.dumps({"inputs": inp, "rows": report, "total": total}, indent=2))
    preview = make_preview(job, out_clips, inp["audio"], offsets)
    unmatched = sum(1 for r in report for h in r["how"] if h.startswith("unmatched"))
    return {"job": str(job), "edit": str(job / "edit.json"), "preview": str(preview), "duration": round(total, 2),
            "clips": len(out_clips), "scenes": len(set(assign)), "builds": sum(len(r["how"]) for r in report),
            "unmatched_builds": unmatched}


def make_preview(job, out_clips, audio, offsets):
    """Quick MP4 (ffmpeg, no Premiere) to review timing before the real build."""
    lst = job / "work" / "concat.txt"
    lst.write_text("".join(f"file '{c['file']}'\n" for c in out_clips))
    out = job / "preview.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    for a in audio:
        cmd += ["-i", a]
    delays = ";".join(f"[{k + 1}:a]adelay={int(off * 1000)}|{int(off * 1000)}[a{k}]" for k, off in enumerate(offsets))
    mix = "".join(f"[a{k}]" for k in range(len(audio))) + f"amix=inputs={len(audio)}:duration=longest:normalize=0,aresample=48000[a]"
    cmd += ["-filter_complex", delays + ";" + mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)]
    subprocess.run(cmd, check=True)
    return out
