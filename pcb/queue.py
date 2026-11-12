"""Away-only queue: Premiere builds run only while the user is away from the Mac.

"Away" = screen locked, every display asleep, screensaver running, or another user on the
console (optionally also idle for `idle_minutes`). A launchd agent calls `pcb queue run` every
minute; it exits immediately unless something is queued and the user is away. A build that has
started finishes even if the user comes back (they take a minute or two).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

from . import premiere
from .build import build
from .config import CFG

KINDS = ("pending", "running", "done", "failed")


def _dirs():
    d = {k: CFG.queue_dir / k for k in KINDS}
    for p in d.values():
        p.mkdir(parents=True, exist_ok=True)
    return d


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(CFG.queue_dir / "runner.log", "a") as f:
        f.write(line + "\n")


def away_state():
    out = subprocess.run([str(CFG.bin_dir / "ppro-hide"), "away"], capture_output=True, text=True, check=True).stdout
    st = json.loads(out)
    reasons = [k for k in ("locked", "displays_asleep", "screensaver") if st[k]]
    if not st["on_console"]:
        reasons.append("other_user_on_console")
    if CFG.idle_minutes and st["idle_seconds"] >= CFG.idle_minutes * 60:
        reasons.append("idle_%dmin" % (st["idle_seconds"] // 60))
    return bool(reasons), reasons, st


def notify(title, text):
    subprocess.run(["osascript", "-e", "display notification %s with title %s" % (json.dumps(text), json.dumps(title))],
                   capture_output=True)


def entries(kind):
    return sorted(f for f in os.listdir(_dirs()[kind]) if f.endswith(".json") and not f.startswith("._"))


def add(spec_path):
    spec_path = os.path.abspath(spec_path)
    name = json.load(open(spec_path)).get("name", os.path.basename(os.path.dirname(spec_path)))
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:80]
    entry = _dirs()["pending"] / ("%s-%s.json" % (time.strftime("%Y%m%d-%H%M%S"), safe))
    entry.write_text(json.dumps({"spec": spec_path, "name": name, "added": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))
    return str(entry)


def status():
    out = {}
    for k in KINDS:
        items = []
        for e in entries(k)[-20:]:
            d = json.loads((_dirs()[k] / e).read_text())
            items.append({"entry": e, "name": d.get("name"), "finished": d.get("finished"), "error": d.get("error"),
                          "project": d.get("project"), "mp4": d.get("mp4")})
        out[k] = items
    return out


def _run_one(entry):
    d = _dirs()
    cur = d["running"] / entry
    shutil.move(str(d["pending"] / entry), cur)
    job = json.loads(cur.read_text())
    log("start: %s" % job["name"])
    t0 = time.time()
    try:
        rep = build(job["spec"], log=log)
        job.update(project=rep["project"], mp4=rep["mp4"], checks=rep["checks"], copied=rep.get("copied"))
        ok = True
    except Exception as e:  # noqa: BLE001 — record any failure on the entry
        job["error"] = "%s: %s" % (type(e).__name__, e)
        job["trace"] = traceback.format_exc()[-3000:]
        ok = False
    job.update(finished=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0, 1))
    (d["done" if ok else "failed"] / entry).write_text(json.dumps(job, indent=2))
    cur.unlink()
    log(("done: %s in %.0fs" % (job["name"], job["seconds"])) if ok else ("FAILED: %s: %s" % (job["name"], job["error"])))
    return ok


def run(force=False):
    """Process the queue if the user is away (or `force`). Returns a summary dict."""
    pending = entries("pending")
    if not pending:
        return {"ran": 0, "reason": "queue empty"}
    is_away, reasons, _ = away_state()
    if not (is_away or force):
        return {"ran": 0, "reason": "user is at the Mac", "pending": len(pending)}
    log("away (%s) — %d job(s) queued" % (", ".join(reasons) or "forced", len(pending)))
    premiere.HIDE_ENABLED = not is_away
    was_running = premiere.running()
    caff = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    ok_n = fail_n = 0
    try:
        for entry in pending:
            if not force and not away_state()[0]:
                log("user is back — pausing the queue")
                break
            if _run_one(entry):
                ok_n += 1
            else:
                fail_n += 1
    finally:
        if not was_running:
            try:
                premiere.quit_premiere()
                log("quit Premiere")
            except Exception as e:  # noqa: BLE001
                log("could not quit Premiere: %s" % e)
        caff.terminate()
    if ok_n or fail_n:
        notify("Premiere queue", "%d video(s) finished%s" % (ok_n, ", %d failed" % fail_n if fail_n else ""))
    return {"ran": ok_n + fail_n, "ok": ok_n, "failed": fail_n}


if __name__ == "__main__":
    print(json.dumps(run(force="--force" in sys.argv), indent=2))
