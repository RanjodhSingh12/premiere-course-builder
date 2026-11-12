# Premiere Course Builder

Turns a folder of **storyboard + slide clips + voiceover** into a finished **Premiere Pro project (`.prproj`) and MP4**, with every slide and every on-screen build timed to the moment it is spoken.

Built for e-learning video production: designers export animated slides (for example from Canva), a voice artist records the script, and this tool does the assembly an editor would do by hand: matching slides to scenes, holding each slide for its narration, and making each bullet appear as its line is read.

It runs on your Mac, with no cloud services: Whisper for speech, macOS Vision for reading slide text, and Premiere for the project file. Premiere is driven in the background, and by default it only runs **while you're away from the screen**.

```
my-video/
  storyboard/Storyboard_Lesson3.docx     Scene | Script | Words | OST | Notes
  canva/1.mp4 … 21.mp4                  slide clips in play order
  audio/audio 1.mp3, audio 2.mp3         voiceover, in name order
        │
        ▼   pcb make my-video
  preview.mp4                            quick ffmpeg preview (seconds)
  output/<title>.prproj + <title>.mp4    real Premiere project + export (queued)
```

## How it works

1. **Transcribe** the voiceover locally with whisper.cpp, with word-level timings.
2. **Find builds** in each slide clip by measuring frame-to-frame change, then **read the text** each build adds with macOS Vision OCR.
3. **Match slides to scenes.** A small dynamic program assigns clips to storyboard scenes, in order, by comparing on-screen text with each scene's title and OST. Several clips can share a scene, as when a hook is split across 3 slides.
4. **Time scenes** to the first words of each scene's script, snapped to the pause before them.
5. **Time builds** to where their words, or the closest paraphrase, are spoken. Each match is the tightest cluster of the slide's content words in the transcript, with number words normalised ("24" = "twenty-four"). Headers that are never read aloud are spaced between their neighbours.
6. **Retime** each clip with ffmpeg: it's cut at its builds, and the still stretches are held or shortened so each build lands 0.15 s before its words. If a Canva export blinks an element out just before the clip ends, that blink is dropped.
7. **Build in Premiere** through a small CEP panel ("Claude Bridge"). The tool lays slides on V1, the voiceover on A1 and a marker per scene, then exports H.264, saves the `.prproj` and checks the results: valid project, exact duration, full decode of the MP4.

Tested on a 6:31 course video (21 Canva clips, 2 audio files, 18 storyboard scenes, 91 builds). Every slide landed within 0.7 s of a hand-timed edit. 84 of 91 builds were within 1.5 s, with a median difference of 0.3 s, and the outliers were placed on the exact spoken words.

## Install (macOS, Apple silicon)

Requirements: Premiere Pro (tested on 2027 / v27), Python 3.11+, Xcode command-line tools (`swiftc`), and Homebrew `ffmpeg` and `whisper-cpp`.

```bash
brew install ffmpeg whisper-cpp
git clone https://github.com/RanjodhSingh12/premiere-course-builder.git
cd premiere-course-builder
./scripts/install.sh
```

`install.sh` does the following:
- creates `.venv` and builds the two Swift helpers (`bin/ocr` and `bin/ppro-hide`)
- installs the Premiere panel and turns on Adobe's CEP debug mode, which unsigned panels need
- copies Premiere's own H.264 "Match Source – High bitrate" export preset into `presets/` (Adobe's file, not redistributed here)
- downloads the Whisper model (`ggml-base.en-q5_1`, 57 MB)
- loads the away-only queue agent (launchd)
- registers the MCP server with Claude Code

Restart Premiere once afterwards, then check the setup:

```bash
.venv/bin/pcb doctor
```

Settings live in `~/.config/pcb/config.toml` (see `config.example.toml`): work folder, Premiere version, timing lead, and an optional idle rule.

## Use

```bash
pcb make ~/Videos/lesson-03                     # plan + preview, Premiere build queued for when you're away
pcb make ~/Videos/lesson-03 --now               # build in Premiere right away
pcb make ~/Videos/lesson-03 --copy-to "~/Videos/lesson-03/handoff"
pcb plan <folder>                               # only plan + preview
pcb queue status | run [--force]
pcb build <edit.json>                           # build any edit spec (format in pcb/build.py)
pcb transcribe <audio>
```

Each job lives in `<work_dir>/jobs/<folder name>/`:
- `plan.json`: every clip's scene, start time and builds, with how each was matched and the OCR text
- `edit.json`: the Premiere edit spec
- `retimed/`: the retimed slide clips
- `preview.mp4`: a quick ffmpeg preview
- `output/`: the `.prproj`, `.mp4` and `report.json`

### Away-only building

Premiere can't be fully hidden while it works. Even when it's hidden and never takes focus, it flashes its windows for about 0.4 s per build. So by default, builds wait in a queue. A launchd agent checks every minute and runs them only while the screen is locked, the displays are asleep or the screensaver is on, then quits Premiere and posts a notification. Use `--now` or `pcb queue run --force` to build immediately.

## Use from Claude (MCP)

`install.sh` registers the server. To do it by hand:

```bash
claude mcp add premiere-course-builder -s user -- "$PWD/.venv/bin/python" -m pcb.mcp_server
```

| Tool | What it does |
|---|---|
| `inspect_folder` | finds the storyboard, slide clips and audio in a folder |
| `plan_video` | transcribes, matches, retimes; returns the preview and edit spec |
| `build_premiere` | builds the `.prproj` + MP4, queued (default) or `now`, with optional `copy_to` |
| `queue_status` / `run_queue_now` | shows or runs the away-only queue |
| `transcribe_audio` | local Whisper transcript with word timings |
| `check_setup` / `premiere_status` | checks the install and whether Premiere and the bridge are up |

Then ask Claude: *"Make the video in ~/Videos/lesson-03 and copy the project into its handoff folder."*

## Repository layout

```
pcb/            Python package
  assemble.py   folder → plan → retimed clips → edit.json + preview   (the matching logic)
  build.py      edit.json → Premiere project + MP4, verified
  premiere.py   file-queue client for the bridge panel; hidden start/quit
  queue.py      away-only queue
  transcribe.py whisper.cpp wrapper (cached word timings)
  storyboard.py .docx storyboard reader (no dependencies)
  video.py      build detection + OCR of each build
  cli.py, mcp_server.py
bridge/         Premiere CEP panel ("Claude Bridge") + ExtendScript helpers (host/host.jsx)
swift/          ocr.swift (macOS Vision), ppro-hide.swift (hide guard + away detection)
presets/        H.264 export preset (copied from your Premiere install by install.sh)
launchd/        queue agent template
extras/slide-rebuild/  rebuild slides as HTML, render in headless Chromium, and compare timings with a reference video
tests/          matching unit tests (no media needed)
```

## Notes and limits

- ExtendScript is ES3. In `host.jsx`, object keys can't be reserved words (`{export: 1}` fails), and there's no `JSON` object (use `CB.stringify`).
- An AppleScript `quit` hangs Premiere 2027, so the tool quits from inside Premiere (`app.quit()`).
- The bridge has no network port. Jobs are files in `~/Library/Application Support/ClaudePremiereBridge`, so only your Mac user can drive Premiere.
- Animations stay baked into each slide clip. Editors can move, trim or swap whole slides in the `.prproj`, but they can't change an individual bullet's animation there.
- Scripts aren't always read word for word, so builds whose text is never spoken (labels like "Scenario", "Determine how you:") are spaced evenly. See `how` in `plan.json`.
