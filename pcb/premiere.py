"""Talk to Premiere Pro through the Claude Bridge panel (bridge/), without showing it on screen.

The panel watches a folder for ExtendScript jobs (no network port) and writes results back:
    ~/Library/Application Support/ClaudePremiereBridge/{inbox,outbox,status.json}

    from pcb.premiere import run
    run("return app.version;")      # body of a function; its return value comes back as JSON
"""
import contextlib
import json
import os
import subprocess
import time
import uuid

from .config import CFG

ROOT = os.path.expanduser("~/Library/Application Support/ClaudePremiereBridge")
INBOX = os.path.join(ROOT, "inbox")
OUTBOX = os.path.join(ROOT, "outbox")
HOST_JSX = os.path.expanduser(
    "~/Library/Application Support/Adobe/CEP/extensions/com.starweaver.claudebridge/host/host.jsx")
HIDE = str(CFG.bin_dir / "ppro-hide")

# The away-only queue switches this off: nobody is watching, and the guard would need an
# Automation permission prompt that nobody is there to answer.
HIDE_ENABLED = os.environ.get("PCB_NO_HIDE") != "1"


class PremiereError(RuntimeError):
    pass


def alive(max_age=10):
    """True if the bridge panel wrote a heartbeat in the last `max_age` seconds."""
    try:
        with open(os.path.join(ROOT, "status.json")) as f:
            return (time.time() * 1000 - json.load(f)["ts"]) < max_age * 1000
    except (OSError, ValueError, KeyError):
        return False


def running():
    return subprocess.run(["pgrep", "-f", "MacOS/%s$" % CFG.premiere_app], capture_output=True).returncode == 0


@contextlib.contextmanager
def kept_hidden():
    """Re-hide Premiere the moment any of its windows appears, for the duration of the block."""
    if not HIDE_ENABLED or not os.path.exists(HIDE):
        yield
        return
    stop = os.path.join(ROOT, "guard-stop-%d-%s" % (os.getpid(), uuid.uuid4().hex[:6]))
    env = dict(os.environ, PCB_PREMIERE_APP=CFG.premiere_app, PCB_PREMIERE_BUNDLE=CFG.premiere_bundle_id)
    g = subprocess.Popen([HIDE, "guard", stop], env=env)
    try:
        yield
    finally:
        open(stop, "w").close()
        try:
            g.wait(timeout=15)
        except subprocess.TimeoutExpired:
            g.kill()


def ensure_running(timeout=180):
    """Start Premiere in the background (no focus, hidden) if it isn't running yet."""
    if alive():
        return
    with kept_hidden():
        if not running():
            subprocess.run(["open", "-g", "-j", "-a", CFG.premiere_app], check=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if alive(max_age=4):
                time.sleep(2)
                return
            time.sleep(1)
    raise PremiereError("Premiere started but the Claude Bridge panel did not come up within %ss" % timeout)


def quit_premiere():
    """Quit from inside Premiere (an AppleScript `quit` hangs on Premiere 2027)."""
    if alive():
        run("app.quit(); return true;", start=False)


def reload_host():
    """Premiere may have been open since before host.jsx changed: load the current helpers."""
    run("$.evalFile(new File(%s)); 'ok'" % json.dumps(HOST_JSX), raw=True)


def run(body, timeout=900, raw=False, start=True):
    """Run ExtendScript in Premiere and return its result (Premiere is started and kept hidden)."""
    if start:
        ensure_running()
    if not alive():
        raise PremiereError("the Claude Bridge panel is not running in Premiere")
    with kept_hidden():
        return _run(body, timeout, raw)


def _run(body, timeout, raw):
    os.makedirs(INBOX, exist_ok=True)
    job = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    code = body if raw else "CB.run(function(){\n%s\n})" % body
    tmp = os.path.join(INBOX, job + ".tmp")
    with open(tmp, "w") as f:
        f.write(code)
    os.rename(tmp, os.path.join(INBOX, job + ".jsx"))
    out = os.path.join(OUTBOX, job + ".json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(out):
            with open(out) as f:
                res = json.load(f)
            os.remove(out)
            if "bridgeError" in res:
                raise PremiereError("bridge: " + res["bridgeError"])
            if raw:
                return res.get("raw")
            try:
                parsed = json.loads(res.get("raw"))
            except (TypeError, ValueError):
                raise PremiereError("unexpected reply from Premiere: %r" % (res.get("raw"),))
            if not parsed.get("ok"):
                raise PremiereError(parsed.get("error"))
            return parsed.get("result")
        time.sleep(0.2)
    raise PremiereError("timed out after %ss waiting for job %s" % (timeout, job))
