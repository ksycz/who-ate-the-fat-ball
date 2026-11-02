#!/usr/bin/env bash
# Install (or reinstall) the LaunchAgent that runs `fatball serve` at login and keeps it running.
# Usage: scripts/install-launchagent.sh
set -euo pipefail

LABEL="com.whoatethefatball"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${FATBALL_DATA_DIR:-$HOME/Library/Application Support/WhoAteTheFatBall}"
LOG_DIR="$DATA_DIR/logs"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV="$(command -v uv || true)"

if [[ -z "$UV" ]]; then
  echo "uv not found on PATH; install it first (https://docs.astral.sh/uv/)." >&2
  exit 1
fi

xml_escape() {
  local s="$1"
  s="${s//&/&amp;}"
  s="${s//</&lt;}"
  s="${s//>/&gt;}"
  printf '%s' "$s"
}

mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml_escape "$UV")</string>
    <string>run</string>
    <string>--project</string>
    <string>$(xml_escape "$REPO_DIR")</string>
    <string>fatball</string>
    <string>serve</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml_escape "$REPO_DIR")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>FATBALL_DATA_DIR</key>
    <string>$(xml_escape "$DATA_DIR")</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$(xml_escape "$LOG_DIR/fatball.out.log")</string>
  <key>StandardErrorPath</key>
  <string>$(xml_escape "$LOG_DIR/fatball.err.log")</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
echo "Installed $PLIST; fatball serve now runs at login. Logs: $LOG_DIR"
