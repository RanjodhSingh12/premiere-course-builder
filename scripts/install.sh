#!/bin/bash
# One-time setup on a Mac with Premiere Pro, ffmpeg and whisper.cpp (brew install ffmpeg whisper-cpp).
#   ./scripts/install.sh            venv, helpers, Premiere bridge, Whisper model, queue agent, MCP
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "== Python venv"
python3 -m venv .venv
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -e .

echo "== Swift helpers (OCR via macOS Vision, Premiere hide/away tool)"
mkdir -p bin
swiftc -O -o bin/ocr swift/ocr.swift
swiftc -O -o bin/ppro-hide swift/ppro-hide.swift

echo "== Config"
mkdir -p ~/.config/pcb
[ -f ~/.config/pcb/config.toml ] || cp config.example.toml ~/.config/pcb/config.toml
echo "   edit ~/.config/pcb/config.toml to change work_dir / Premiere version"

echo "== Premiere bridge panel (CEP)"
# Unsigned panels load only with CEP debug mode on (an Adobe CEP preference, per CSXS version).
for v in 11 12 13; do defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1; done
DEST="$HOME/Library/Application Support/Adobe/CEP/extensions/com.starweaver.claudebridge"
rm -rf "$DEST"; mkdir -p "$(dirname "$DEST")"
rsync -a --exclude '._*' bridge/com.starweaver.claudebridge/ "$DEST/"
mkdir -p "$HOME/Library/Application Support/ClaudePremiereBridge"
chmod 700 "$HOME/Library/Application Support/ClaudePremiereBridge"

echo "== Export preset (Premiere's own, copied from your install)"
mkdir -p presets
EPR=$(find "/Applications" -maxdepth 10 -path "*Premiere Pro*" -name "Match Source - Adaptive High Bitrate.epr" 2>/dev/null | head -1)
if [ -n "$EPR" ]; then cp "$EPR" "presets/H264 Match Source High.epr"; else echo "   preset not found: export one from Premiere as presets/H264 Match Source High.epr"; fi

echo "== Whisper model"
.venv/bin/python -c "from pcb.transcribe import ensure_model; print('   ', ensure_model())"

echo "== Away-only queue (launchd, every 60 s)"
PLIST="$HOME/Library/LaunchAgents/com.pcb.premiere-queue.plist"
sed -e "s#__PYTHON__#$REPO/.venv/bin/python#g" -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" \
    launchd/com.pcb.premiere-queue.plist.template > "$PLIST"
launchctl bootout "gui/$(id -u)/com.pcb.premiere-queue" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "== MCP server for Claude Code"
if command -v claude >/dev/null; then
  claude mcp remove premiere-course-builder -s user >/dev/null 2>&1 || true
  claude mcp add premiere-course-builder -s user -- "$REPO/.venv/bin/python" -m pcb.mcp_server
else
  echo "   claude CLI not found; register manually:"
  echo "   claude mcp add premiere-course-builder -s user -- $REPO/.venv/bin/python -m pcb.mcp_server"
fi

echo
echo "Done. Restart Premiere once so it loads the bridge panel, then run:  .venv/bin/pcb doctor"
