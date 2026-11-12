"""pcb — Premiere Course Builder.

    pcb make <folder> [--now] [--copy-to DIR]   plan + preview, then queue the Premiere build (or build now)
    pcb plan <folder>                           only plan: retimed clips, edit.json, preview.mp4
    pcb build <edit.json>                       build a Premiere project + MP4 from an edit spec now
    pcb queue add <edit.json> | status | run [--force]
    pcb transcribe <audio>                      word-timed transcript (whisper.cpp)
    pcb doctor                                  check the setup
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

from . import assemble, premiere
from . import queue as Q
from .build import build
from .config import CFG, CONFIG_PATH
from .transcribe import transcribe


def doctor():
    checks = {
        "config": str(CONFIG_PATH) + (" (found)" if CONFIG_PATH.exists() else " (defaults)"),
        "work_dir": str(CFG.work_dir),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "whisper": bool(shutil.which(CFG.whisper_bin)),
        "whisper_model": CFG.whisper_model.exists(),
        "ocr_tool": (CFG.bin_dir / "ocr").exists(),
        "hide_tool": (CFG.bin_dir / "ppro-hide").exists(),
        "premiere_installed": os.path.exists(f"/Applications/{CFG.premiere_app}/{CFG.premiere_app}.app"),
        "bridge_installed": os.path.exists(premiere.HOST_JSX),
        "premiere_running": premiere.running(),
        "bridge_alive": premiere.alive(),
    }
    return checks


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pcb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("folder")
    m.add_argument("--now", action="store_true", help="build in Premiere right away (brief window flashes)")
    m.add_argument("--copy-to", help="also copy the .prproj + .mp4 here")
    p = sub.add_parser("plan")
    p.add_argument("folder")
    b = sub.add_parser("build")
    b.add_argument("edit")
    q = sub.add_parser("queue")
    q.add_argument("action", choices=["add", "status", "run"])
    q.add_argument("edit", nargs="?")
    q.add_argument("--force", action="store_true")
    t = sub.add_parser("transcribe")
    t.add_argument("audio")
    sub.add_parser("doctor")
    a = ap.parse_args(argv)

    if a.cmd in ("make", "plan"):
        res = assemble.plan(a.folder)
        if a.cmd == "make":
            if a.copy_to:
                spec = json.load(open(res["edit"]))
                spec["copy_to"] = a.copy_to
                json.dump(spec, open(res["edit"], "w"), indent=2)
            if a.now:
                res["build"] = build(res["edit"])
            else:
                res["queued"] = Q.add(res["edit"])
        print(json.dumps(res, indent=2, default=str))
    elif a.cmd == "build":
        print(json.dumps(build(a.edit), indent=2, default=str))
    elif a.cmd == "queue":
        if a.action == "add":
            print(Q.add(a.edit))
        elif a.action == "status":
            print(json.dumps(Q.status(), indent=2))
        else:
            print(json.dumps(Q.run(force=a.force), indent=2))
    elif a.cmd == "transcribe":
        print(" ".join(w["raw"] for w in transcribe(a.audio)))
    elif a.cmd == "doctor":
        print(json.dumps(doctor(), indent=2))


if __name__ == "__main__":
    sys.exit(main())
