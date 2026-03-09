#!/bin/bash
# Build OpenClaw deployment tarball (Linux/macOS).
# Usage:
#   ./build_openclaw_bundle.sh
#   SKILLS_DIR=/path/to/clawd/skills ./build_openclaw_bundle.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROBIN_ROOT="$(dirname "$SCRIPT_DIR")"
SKILLS_DIR="${SKILLS_DIR:-$HOME/clawd/skills}"
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

echo "Creating tarball..."
tar -czf "$OUTPUT_DIR/$BUNDLE_NAME" -C "$STAGING" openclaw_bundle
rm -rf "$STAGING"

echo "Created: $OUTPUT_DIR/$BUNDLE_NAME"
