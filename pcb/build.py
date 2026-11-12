"""Build a Premiere project (.prproj) + MP4 from an edit spec, then verify both.

Spec (JSON; times in seconds):
{
  "name": "Lesson 3 final",
  "output_dir": "/path/out",               # default: folder of the spec
  "media": ["/path/a.mp4", "/path/vo.mp3"],
  "sequence_from": 0,                       # media index that sets sequence size / fps
  "clips": [{"media": 0, "in": 0, "out": 12.5, "at": 0.0, "gain_db": 0}],   # video (+linked audio) on V1
  "audio": [{"media": 1, "at": 0}],         # audio-only placements on A1
  "captions": "/path/captions.srt",         # optional (.vtt converted)
  "markers": [{"time": 0, "name": "Intro"}],
  "export": true,
  "preset": "/path/preset.epr",             # default: presets/H264 Match Source High.epr
  "copy_to": "/path/handoff",               # optional: copy .prproj + .mp4 here (byte-verified)
  "overwrite": false
}
"""
import filecmp
import json
import os
import re
import shutil
import subprocess

from . import media as M
from .config import CFG
from .premiere import ensure_running, reload_host, run


class BuildError(RuntimeError):
    pass


def build(spec_path, log=print):
    spec = json.load(open(spec_path))
    name = spec["name"]
    out_dir = os.path.abspath(spec.get("output_dir") or os.path.dirname(os.path.abspath(spec_path)))
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[/:*?"<>|]', "-", name)

    media = [os.path.abspath(p) for p in spec["media"]]
    durs = []
    for p in media:
        if not os.path.isfile(p):
            raise BuildError("missing media: " + p)
        durs.append(M.duration(p))
    for i, c in enumerate(spec["clips"]):
        if not (0 <= c["in"] < c["out"] <= durs[c["media"]] + 0.05):
            raise BuildError("clip %d: in/out %s-%s outside 0-%.2f of %s" % (i, c["in"], c["out"], durs[c["media"]], media[c["media"]]))
    if all("at" not in c for c in spec["clips"]):
        expected = sum(c["out"] - c["in"] for c in spec["clips"])
    else:
        expected = max(c["at"] + c["out"] - c["in"] for c in spec["clips"])

    captions = spec.get("captions")
    if captions:
        if not os.path.isfile(captions):
            raise BuildError("missing captions: " + captions)
        if captions.lower().endswith(".vtt"):
            captions = M.vtt_to_srt(captions, os.path.join(out_dir, safe + ".captions.srt"))

    job = {
        "name": name,
        "project": os.path.join(out_dir, safe + ".prproj"),
        "media": media,
        "sequence_from": spec.get("sequence_from", 0),
        "clips": spec["clips"],
        "markers": spec.get("markers", []),
        "audio": spec.get("audio", []),
        "captions": os.path.abspath(captions) if captions else None,
        "export": os.path.join(out_dir, safe + ".mp4") if spec.get("export", True) else None,
        "preset": os.path.abspath(spec.get("preset") or CFG.export_preset),
        "overwrite": bool(spec.get("overwrite")),
        "close": spec.get("close", True),
    }
    if job["export"] and os.path.exists(job["export"]):
        if not job["overwrite"]:
            raise BuildError('output exists (set "overwrite": true): ' + job["export"])
        os.remove(job["export"])

    ensure_running()
    reload_host()
    log("building in Premiere: " + name)
    summary = run("return CB.buildEdit(%s);" % json.dumps(job), timeout=3 * 3600)

    checks = {"prproj_exists": os.path.isfile(job["project"])}
    checks["prproj_gzip_ok"] = subprocess.run(["gzip", "-t", job["project"]]).returncode == 0
    if job["export"]:
        mp4 = job["export"]
        checks["mp4_exists"] = os.path.isfile(mp4)
        if checks["mp4_exists"]:
            d = M.duration(mp4)
            checks["mp4_duration"] = round(d, 3)
            checks["duration_matches_edit"] = abs(d - expected) < 0.2
            checks["mp4_full_decode_ok"] = M.decodes_cleanly(mp4)
    report = {"spec": os.path.abspath(spec_path), "premiere": summary, "checks": checks,
              "project": job["project"], "mp4": job["export"]}

    bad = [k for k, v in checks.items() if v is False]
    if not bad and spec.get("copy_to"):
        dest = spec["copy_to"]
        os.makedirs(dest, exist_ok=True)
        report["copied"] = []
        for f in [job["project"]] + ([job["export"]] if job["export"] else []):
            target = os.path.join(dest, os.path.basename(f))
            shutil.copy2(f, target)
            if not filecmp.cmp(f, target, shallow=False):
                bad.append("copy_verify:" + target)
            report["copied"].append(target)
    with open(os.path.join(out_dir, safe + ".report.json"), "w") as f:
        json.dump(report, f, indent=2)
    if bad:
        raise BuildError("failed checks: " + ", ".join(bad))
    return report
