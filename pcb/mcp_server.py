"""MCP server: lets Claude (or any MCP client) build course videos with this tool.

Register with Claude Code:
    claude mcp add premiere-course-builder -- /path/to/repo/.venv/bin/python -m pcb.mcp_server
"""
import json
import os

from mcp.server.mcpserver import MCPServer

from . import assemble, premiere
from . import queue as Q
from .build import build
from .cli import doctor
from .transcribe import transcribe

mcp = MCPServer("premiere-course-builder")


@mcp.tool()
def inspect_folder(folder: str) -> dict:
    """List what a video folder contains: the storyboard .docx, the slide clips (in play order) and
    the voiceover files. Run this first to confirm the folder is complete."""
    return assemble.find_inputs(folder)


@mcp.tool()
def plan_video(folder: str) -> dict:
    """Plan a video from a folder (storyboard + slide clips + voiceover): transcribe the voiceover,
    match every slide and every animation build to the words being spoken, retime the clips and
    write a Premiere edit spec plus a quick preview MP4. Takes a few minutes for a 6-minute video.
    Returns the job folder, edit spec path, preview path and how many builds could not be matched."""
    return assemble.plan(folder, log=lambda *a: None)


@mcp.tool()
def build_premiere(edit_spec: str, when: str = "queue", copy_to: str = "") -> dict:
    """Turn an edit spec (from plan_video) into a Premiere Pro project (.prproj) + MP4.
    when="queue" (default) waits until the user is away from the Mac (screen locked / display asleep)
    so nothing appears on their screen; when="now" builds immediately (Premiere stays hidden but can
    flash for about a second). copy_to: optional folder to receive copies of the .prproj and .mp4."""
    if copy_to:
        spec = json.load(open(edit_spec))
        spec["copy_to"] = copy_to
        json.dump(spec, open(edit_spec, "w"), indent=2)
    if when == "now":
        return build(edit_spec, log=lambda *a: None)
    return {"queued": Q.add(edit_spec), "note": "builds the next time the screen is locked or the display sleeps"}


@mcp.tool()
def queue_status() -> dict:
    """Show the away-only Premiere queue: pending, running, done (with output paths) and failed jobs."""
    return Q.status()


@mcp.tool()
def run_queue_now() -> dict:
    """Build everything in the queue right now, even though the user is at the Mac."""
    return Q.run(force=True)


@mcp.tool()
def transcribe_audio(audio_path: str) -> dict:
    """Transcribe a voiceover file locally with Whisper. Returns the text and word timings."""
    words = transcribe(audio_path)
    return {"text": " ".join(w["raw"] for w in words), "words": [{"w": w["raw"], "t": w["t"]} for w in words]}


@mcp.tool()
def check_setup() -> dict:
    """Check that ffmpeg, Whisper, the OCR/hide helpers, Premiere and its bridge panel are ready."""
    return doctor()


@mcp.tool()
def premiere_status() -> dict:
    """Is Premiere running, and is the bridge panel responding?"""
    return {"running": premiere.running(), "bridge_alive": premiere.alive(),
            "version": premiere.run("return app.version;", start=False) if premiere.alive() else None}


def main():
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    mcp.run()


if __name__ == "__main__":
    main()
