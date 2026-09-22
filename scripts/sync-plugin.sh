#!/usr/bin/env bash
# Payload for Cursor local install and Claude marketplace add.
# Do not sync the live .artifacts/ store.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-${HOME}/.cursor/plugins/local/adaptive-artifacts}"

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
mkdir -p \
  "$DEST/bin" \
  "$DEST/hooks" \
  "$DEST/tools/runtime" \
  "$DEST/design/contracts" \
  "$DEST/skills" \
  "$DEST/.claude-plugin" \
  "$DEST/.cursor-plugin"

cp -a "$ROOT/skills/." "$DEST/skills/"
cp -a "$ROOT/hooks/." "$DEST/hooks/"
cp -a "$ROOT/tools/artifacts.py" "$DEST/tools/"
cp -a "$ROOT/tools/runtime/"*.py "$DEST/tools/runtime/"
cp -a "$ROOT/design/contracts/." "$DEST/design/contracts/"
cp -a "$ROOT/bin/adaptive-artifacts" "$DEST/bin/"
cp -a "$ROOT/.claude-plugin/plugin.json" "$ROOT/.claude-plugin/marketplace.json" "$DEST/.claude-plugin/"
cp -a "$ROOT/.cursor-plugin/plugin.json" "$DEST/.cursor-plugin/"
cp -a "$ROOT/README.md" "$DEST/"
cp -a "$ROOT/design/DESIGN.md" "$DEST/design/"

printf '%s\n' "$DEST"
