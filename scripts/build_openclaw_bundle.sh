#!/bin/bash
# Build OpenClaw deployment tarball (Linux/macOS).
# Usage:
#   ./build_openclaw_bundle.sh
#   SKILLS_DIR=/path/to/clawd/skills ./build_openclaw_bundle.sh
#
# Env vars:
#   SKILLS_DIR        - Path to skills tree (default: $HOME/clawd/skills)
#   OPENCLAW_STATE_DIR - OpenClaw state dir to bundle cron + config from (default: $HOME/.openclaw)
#   OUTPUT_DIR        - Where to write the tarball (default: <robin>/dist)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROBIN_ROOT="$(dirname "$SCRIPT_DIR")"
SKILLS_DIR="${SKILLS_DIR:-$HOME/clawd/skills}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROBIN_ROOT/dist}"
BUNDLE_NAME="openclaw-deploy-$(date +%Y%m%d-%H%M%S).tar.gz"

EXCLUDE_ROBIN=".git .venv venv __pycache__ .pytest_cache .mypy_cache .ruff_cache dist"
EXCLUDE_SKILLS=".git __pycache__ .pytest_cache .mypy_cache .ruff_cache"

if [ ! -d "$ROBIN_ROOT" ]; then
  echo "Robin root not found: $ROBIN_ROOT" >&2
  exit 1
fi
if [ ! -d "$SKILLS_DIR" ]; then
  echo "Skills dir not found: $SKILLS_DIR" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
STAGING="$OUTPUT_DIR/_bundle_staging"
rm -rf "$STAGING"
mkdir -p "$STAGING/openclaw_bundle/robin" "$STAGING/openclaw_bundle/skills"

robin_excludes=""
for x in $EXCLUDE_ROBIN; do
  robin_excludes="$robin_excludes --exclude=$x"
done
skills_excludes=""
for x in $EXCLUDE_SKILLS; do
  skills_excludes="$skills_excludes --exclude=$x"
done

echo "Adding robin..."
(cd "$ROBIN_ROOT" && tar cf - $robin_excludes --exclude='*.pyc' --exclude='*.pyo' .) \
  | (cd "$STAGING/openclaw_bundle/robin" && tar xf -)

echo "Adding skills..."
(cd "$SKILLS_DIR" && tar cf - $skills_excludes --exclude='*.pyc' --exclude='*.pyo' .) \
  | (cd "$STAGING/openclaw_bundle/skills" && tar xf -)

if [ -f "$SCRIPT_DIR/configure_openclaw_node.sh" ]; then
  echo "Adding configure script to bundle root..."
  tr -d '\r' < "$SCRIPT_DIR/configure_openclaw_node.sh" > "$STAGING/openclaw_bundle/configure_openclaw_node.sh"
  chmod +x "$STAGING/openclaw_bundle/configure_openclaw_node.sh"
fi

# Bundle cron jobs if available
CRON_SRC="$OPENCLAW_STATE_DIR/cron/jobs.json"
if [ -f "$CRON_SRC" ]; then
  echo "Adding cron jobs..."
  mkdir -p "$STAGING/openclaw_bundle/cron"
  cp "$CRON_SRC" "$STAGING/openclaw_bundle/cron/jobs.json"
else
  echo "No cron jobs found at $CRON_SRC (skipping)."
fi

# Bundle mcporter config if available
MCPORTER_SRC="$OPENCLAW_STATE_DIR/workspace/config/mcporter.json"
if [ -f "$MCPORTER_SRC" ]; then
  echo "Adding mcporter config..."
  mkdir -p "$STAGING/openclaw_bundle/config"
  cp "$MCPORTER_SRC" "$STAGING/openclaw_bundle/config/mcporter.json"
else
  echo "No mcporter config found at $MCPORTER_SRC (skipping)."
fi

# Bundle workspace memory (templates: params, learning-state, equity-snapshots, etc.)
MEMORY_SRC="$OPENCLAW_STATE_DIR/workspace/memory"
if [ -d "$MEMORY_SRC" ]; then
  echo "Adding memory templates..."
  mkdir -p "$STAGING/openclaw_bundle/memory"
  (cd "$MEMORY_SRC" && tar cf - .) | (cd "$STAGING/openclaw_bundle/memory" && tar xf -)
else
  echo "No memory dir found at $MEMORY_SRC (skipping)."
fi

echo "Creating tarball..."
tar -czf "$OUTPUT_DIR/$BUNDLE_NAME" -C "$STAGING" openclaw_bundle
rm -rf "$STAGING"

echo "Created: $OUTPUT_DIR/$BUNDLE_NAME"
