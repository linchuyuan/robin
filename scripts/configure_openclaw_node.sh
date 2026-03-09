#!/usr/bin/env sh
# Configure OpenClaw + Robin MCP on a compute node (Linux/macOS).
# One-click install: handles Node.js, Python venv, npm packages, bundle
# extraction, config files, WhatsApp login, and Codex OAuth.
#
# Usage:
#   ./configure_openclaw_node.sh /path/to/openclaw-deploy-YYYYMMDD-HHMMSS.tar.gz
#   OPENCLAW_CRON_EXPR="0 7 * * *" OPENCLAW_CRON_MESSAGE="Morning brief" \
#     ./configure_openclaw_node.sh /path/to/bundle.tar.gz /opt/openclaw
#
# Safe to pipe through tr for CRLF removal:
#   tr -d '\r' < configure_openclaw_node.sh | bash -s -- /path/to/bundle.tar.gz

set -e

BUNDLE_PATH="${1:?Usage: $0 <path-to-bundle.tar.gz> [install_root]}"
INSTALL_ROOT="${2:-/opt/openclaw}"
PYTHON_EXE="${PYTHON_EXE:-python3}"
ROBIN_MCP_HOST="${ROBIN_MCP_HOST:-127.0.0.1}"
ROBIN_MCP_PORT="${ROBIN_MCP_PORT:-8000}"
ROBIN_MCP_PATH="${ROBIN_MCP_PATH:-/messages}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$OPENCLAW_STATE_DIR/workspace}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_STATE_DIR/openclaw.json}"
INSTALL_MCPORTER="${INSTALL_MCPORTER:-1}"
RUN_CODEX_OAUTH="${RUN_CODEX_OAUTH:-1}"
RUN_WHATSAPP_LOGIN="${RUN_WHATSAPP_LOGIN:-1}"
WHATSAPP_DM_POLICY="${WHATSAPP_DM_POLICY:-pairing}"
WHATSAPP_ALLOW_FROM="${WHATSAPP_ALLOW_FROM:-}"
WHATSAPP_GROUP_POLICY="${WHATSAPP_GROUP_POLICY:-allowlist}"
WHATSAPP_GROUP_ALLOW_FROM="${WHATSAPP_GROUP_ALLOW_FROM:-$WHATSAPP_ALLOW_FROM}"
OPENCLAW_CRON_NAME="${OPENCLAW_CRON_NAME:-}"
OPENCLAW_CRON_EXPR="${OPENCLAW_CRON_EXPR:-}"
OPENCLAW_CRON_TZ="${OPENCLAW_CRON_TZ:-}"
OPENCLAW_CRON_SESSION="${OPENCLAW_CRON_SESSION:-isolated}"
OPENCLAW_CRON_MESSAGE="${OPENCLAW_CRON_MESSAGE:-}"
OPENCLAW_CRON_CHANNEL="${OPENCLAW_CRON_CHANNEL:-}"
OPENCLAW_CRON_TO="${OPENCLAW_CRON_TO:-}"
START_GATEWAY_FOR_CRON="${START_GATEWAY_FOR_CRON:-1}"

export OPENCLAW_STATE_DIR

# ── Helpers ──────────────────────────────────────────────────────────────────

json_array_from_csv() {
  input="$1"
  if [ -z "$input" ]; then
    printf '[]'
    return
  fi

  old_ifs=$IFS
  IFS=','
  set -- $input
  IFS=$old_ifs

  first=1
  printf '['
  for item in "$@"; do
    trimmed=$(printf '%s' "$item" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    if [ -z "$trimmed" ]; then
      continue
    fi
    escaped=$(printf '%s' "$trimmed" | sed 's/\\/\\\\/g; s/"/\\"/g')
    if [ "$first" -eq 0 ]; then
      printf ', '
    fi
    printf '"%s"' "$escaped"
    first=0
  done
  printf ']'
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

# Resolve a TTY for interactive commands (works even when piped via tr|bash).
get_tty() {
  if [ -e /dev/tty ]; then
    echo /dev/tty
  else
    echo /dev/null
  fi
}

# Run an interactive command with a timeout so it can't hang forever.
# Usage: run_interactive <timeout_secs> <command> [args...]
run_interactive() {
  _timeout="$1"; shift
  _tty=$(get_tty)
  if [ "$_tty" = "/dev/null" ]; then
    echo "  Skipped (no terminal available). Run manually: $*"
    return 0
  fi
  if command -v timeout >/dev/null 2>&1; then
    timeout "$_timeout" "$@" <"$_tty" || {
      _rc=$?
      if [ "$_rc" -eq 124 ]; then
        echo "  Timed out after ${_timeout}s (auth may have completed). If needed, run manually: $*"
      else
        echo "  Exited with code $_rc. Run manually if needed: $*"
      fi
      return 0
    }
  else
    "$@" <"$_tty" || {
      echo "  Exited with error. Run manually if needed: $*"
      return 0
    }
  fi
}

# ── Preflight checks ────────────────────────────────────────────────────────

if [ ! -f "$BUNDLE_PATH" ]; then
  echo "Bundle file not found: $BUNDLE_PATH" >&2
  exit 1
fi

require_cmd tar
require_cmd curl

# ── 1. Python + venv ────────────────────────────────────────────────────────

if ! command -v "$PYTHON_EXE" >/dev/null 2>&1; then
  echo "Python3 not found. Installing..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y python3 python3-pip
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip
  elif command -v brew >/dev/null 2>&1; then
    brew install python3
  else
    echo "Cannot auto-install Python3. Please install manually and rerun." >&2
    exit 1
  fi
  hash -r
fi
require_cmd "$PYTHON_EXE"

if ! "$PYTHON_EXE" -m ensurepip --version >/dev/null 2>&1; then
  PY_VER=$("$PYTHON_EXE" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "3")
  echo "python3-venv not available. Installing python${PY_VER}-venv..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y "python${PY_VER}-venv" || apt-get install -y python3-venv
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3-virtualenv || true
  fi
fi

# ── 2. Node.js >= 22 ────────────────────────────────────────────────────────

MIN_NODE_MAJOR=22
current_node_major=0
if command -v node >/dev/null 2>&1; then
  current_node_major=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
fi
if [ "$current_node_major" -lt "$MIN_NODE_MAJOR" ] 2>/dev/null; then
  echo "Node.js v${MIN_NODE_MAJOR}+ required (current: ${current_node_major:-none}). Installing..."
  if command -v apt-get >/dev/null 2>&1; then
    curl -fsSL "https://deb.nodesource.com/setup_${MIN_NODE_MAJOR}.x" | bash -
    apt-get install -y nodejs
  elif command -v yum >/dev/null 2>&1; then
    curl -fsSL "https://rpm.nodesource.com/setup_${MIN_NODE_MAJOR}.x" | bash -
    yum install -y nodejs
  elif command -v brew >/dev/null 2>&1; then
    brew install "node@${MIN_NODE_MAJOR}"
  else
    echo "Cannot auto-install Node.js ${MIN_NODE_MAJOR}+. Please install manually and rerun." >&2
    exit 1
  fi
  hash -r
  echo "Node.js $(node -v) installed."
else
  echo "Node.js v${current_node_major} OK (>= ${MIN_NODE_MAJOR})."
fi
require_cmd npm

# ── 3. npm packages ─────────────────────────────────────────────────────────

echo "Installing OpenClaw..."
npm install -g openclaw@latest
if [ "$INSTALL_MCPORTER" = "1" ]; then
  echo "Installing mcporter..."
  npm install -g mcporter@latest
fi

NPM_PREFIX=$(npm prefix -g 2>/dev/null || true)
if [ -n "$NPM_PREFIX" ]; then
  PATH="$NPM_PREFIX/bin:$PATH"
  export PATH
fi

require_cmd openclaw
if [ "$INSTALL_MCPORTER" = "1" ]; then
  require_cmd mcporter
fi

# ── 4. Extract bundle ───────────────────────────────────────────────────────

mkdir -p "$INSTALL_ROOT" "$OPENCLAW_STATE_DIR" "$OPENCLAW_WORKSPACE"
if [ -d "$INSTALL_ROOT/openclaw_bundle" ]; then
  backup_dir="$INSTALL_ROOT/openclaw_bundle.bak.$(date +%Y%m%d-%H%M%S)"
  echo "Backing up existing bundle to $backup_dir"
  mv "$INSTALL_ROOT/openclaw_bundle" "$backup_dir"
fi

echo "Extracting tarball..."
tar -xzf "$BUNDLE_PATH" -C "$INSTALL_ROOT"

BUNDLE_ROOT="$INSTALL_ROOT/openclaw_bundle"
ROBIN_ROOT="$BUNDLE_ROOT/robin"
SKILLS_SRC="$BUNDLE_ROOT/skills"
WORKSPACE_CONFIG_DIR="$OPENCLAW_WORKSPACE/config"

# OpenClaw discovers skills from the global npm skills dir, not ~/.openclaw/workspace/skills.
OPENCLAW_GLOBAL_SKILLS_DIR="${NPM_PREFIX}/lib/node_modules/openclaw/skills"
if [ ! -d "$OPENCLAW_GLOBAL_SKILLS_DIR" ]; then
  # Fallback: try to find it
  OPENCLAW_GLOBAL_SKILLS_DIR="$(node -e "console.log(require('path').join(require.resolve('openclaw/package.json'),'..','skills'))" 2>/dev/null || true)"
fi
if [ ! -d "$OPENCLAW_GLOBAL_SKILLS_DIR" ]; then
  echo "Warning: Could not find OpenClaw global skills directory. Skills will be placed in $OPENCLAW_WORKSPACE/skills as fallback." >&2
  OPENCLAW_GLOBAL_SKILLS_DIR="$OPENCLAW_WORKSPACE/skills"
fi
ROBIN_MCP_BASE_URL="http://$ROBIN_MCP_HOST:$ROBIN_MCP_PORT$ROBIN_MCP_PATH"

if [ ! -d "$ROBIN_ROOT" ]; then
  echo "Expected robin folder not found at $ROBIN_ROOT" >&2
  exit 1
fi
if [ ! -d "$SKILLS_SRC" ]; then
  echo "Expected skills folder not found at $SKILLS_SRC" >&2
  exit 1
fi

# ── 5. Python venv + deps ───────────────────────────────────────────────────

VENV_PATH="$ROBIN_ROOT/.venv"
echo "Creating Robin MCP virtual environment..."
"$PYTHON_EXE" -m venv "$VENV_PATH"

VENV_PYTHON="$VENV_PATH/bin/python"
echo "Installing Robin MCP Python dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROBIN_ROOT/requirements.txt"

# ── 6. Skills (install into OpenClaw's global npm skills dir) ────────────────

echo "Installing bundled skills into $OPENCLAW_GLOBAL_SKILLS_DIR ..."
if [ -d "$SKILLS_SRC" ]; then
  for skill_dir in "$SKILLS_SRC"/*/; do
    skill_name="$(basename "$skill_dir")"
    target="$OPENCLAW_GLOBAL_SKILLS_DIR/$skill_name"
    if [ -d "$target" ]; then
      echo "  Updating: $skill_name"
      rm -rf "$target"
    else
      echo "  Adding:   $skill_name"
    fi
    cp -r "$skill_dir" "$target"
  done
else
  echo "Warning: No skills directory in bundle." >&2
fi

# ── 7. Config files ─────────────────────────────────────────────────────────

mkdir -p "$WORKSPACE_CONFIG_DIR"
MCPORTER_CONFIG_PATH="$WORKSPACE_CONFIG_DIR/mcporter.json"
cat > "$MCPORTER_CONFIG_PATH" <<EOF
{
  "mcpServers": {
    "robinhood": {
      "transport": "streamable-http",
      "baseUrl": "$ROBIN_MCP_BASE_URL"
    }
  },
  "imports": []
}
EOF

whatsapp_allow_from_json=$(json_array_from_csv "$WHATSAPP_ALLOW_FROM")
whatsapp_group_allow_from_json=$(json_array_from_csv "$WHATSAPP_GROUP_ALLOW_FROM")
if [ -f "$OPENCLAW_CONFIG_PATH" ]; then
  config_backup="$OPENCLAW_CONFIG_PATH.bak.$(date +%Y%m%d-%H%M%S)"
  echo "Backing up existing OpenClaw config to $config_backup"
  cp "$OPENCLAW_CONFIG_PATH" "$config_backup"
fi

echo "Writing OpenClaw config..."
mkdir -p "$(dirname "$OPENCLAW_CONFIG_PATH")"
cat > "$OPENCLAW_CONFIG_PATH" <<EOF
{
  "channels": {
    "whatsapp": {
      "dmPolicy": "$WHATSAPP_DM_POLICY",
      "allowFrom": $whatsapp_allow_from_json,
      "groupPolicy": "$WHATSAPP_GROUP_POLICY",
      "groupAllowFrom": $whatsapp_group_allow_from_json
    }
  }
}
EOF

# ── 8. Start scripts ────────────────────────────────────────────────────────

ROBIN_START_SCRIPT="$ROBIN_ROOT/start_mcp.sh"
cat > "$ROBIN_START_SCRIPT" <<EOF
#!/usr/bin/env sh
set -e
export MCP_SERVER_MODE=1
exec "$VENV_PYTHON" "$ROBIN_ROOT/server.py" --transport=streamable-http --host=$ROBIN_MCP_HOST --port=$ROBIN_MCP_PORT --path=$ROBIN_MCP_PATH "\$@"
EOF
chmod +x "$ROBIN_START_SCRIPT"

STACK_START_SCRIPT="$INSTALL_ROOT/start_openclaw_stack.sh"
mkdir -p "$OPENCLAW_STATE_DIR/logs"
cat > "$STACK_START_SCRIPT" <<EOF
#!/usr/bin/env sh
set -e
export OPENCLAW_STATE_DIR="$OPENCLAW_STATE_DIR"
"$ROBIN_START_SCRIPT" > "$OPENCLAW_STATE_DIR/logs/robin-mcp.log" 2>&1 &
echo \$! > "$OPENCLAW_STATE_DIR/robin-mcp.pid"
exec openclaw gateway "\$@"
EOF
chmod +x "$STACK_START_SCRIPT"

# ── 9. Cron (optional) ──────────────────────────────────────────────────────

if [ -n "$OPENCLAW_CRON_EXPR" ] && [ -n "$OPENCLAW_CRON_MESSAGE" ] && [ -n "$OPENCLAW_CRON_NAME" ]; then
  if [ "$START_GATEWAY_FOR_CRON" = "1" ]; then
    if openclaw gateway status >/dev/null 2>&1; then
      echo "OpenClaw gateway already running; reusing it for cron registration."
    else
      echo "Starting OpenClaw gateway in background for cron registration..."
      nohup "$STACK_START_SCRIPT" > "$OPENCLAW_STATE_DIR/logs/openclaw-gateway.log" 2>&1 &
      sleep 5
    fi
  fi

  if [ "$OPENCLAW_CRON_SESSION" = "main" ]; then
    set -- openclaw cron add --name "$OPENCLAW_CRON_NAME" --cron "$OPENCLAW_CRON_EXPR" --session main --system-event "$OPENCLAW_CRON_MESSAGE" --wake now
  else
    set -- openclaw cron add --name "$OPENCLAW_CRON_NAME" --cron "$OPENCLAW_CRON_EXPR" --session isolated --message "$OPENCLAW_CRON_MESSAGE"
    if [ -n "$OPENCLAW_CRON_CHANNEL" ] && [ -n "$OPENCLAW_CRON_TO" ]; then
      set -- "$@" --announce --channel "$OPENCLAW_CRON_CHANNEL" --to "$OPENCLAW_CRON_TO"
    fi
  fi
  if [ -n "$OPENCLAW_CRON_TZ" ]; then
    set -- "$@" --tz "$OPENCLAW_CRON_TZ"
  fi

  echo "Registering OpenClaw cron job..."
  "$@"
fi

# ── 10. WhatsApp + Codex OAuth (interactive, at the end) ────────────────────

echo ""
echo "=== Setup: WhatsApp and Codex OAuth ==="
if [ "$RUN_WHATSAPP_LOGIN" = "1" ]; then
  echo "Linking WhatsApp account (QR or pairing)..."
  run_interactive 120 openclaw channels login --channel whatsapp
fi
if [ "$RUN_CODEX_OAUTH" = "1" ]; then
  echo "Signing in with OpenAI Codex (browser OAuth)..."
  run_interactive 120 openclaw models auth login --provider openai-codex
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  OpenClaw deployment configured."
echo "============================================"
echo "Bundle root:        $BUNDLE_ROOT"
echo "Robin root:         $ROBIN_ROOT"
echo "OpenClaw workspace: $OPENCLAW_WORKSPACE"
echo "Skills dir:         $OPENCLAW_GLOBAL_SKILLS_DIR"
echo "OpenClaw config:    $OPENCLAW_CONFIG_PATH"
echo "mcporter config:    $MCPORTER_CONFIG_PATH"
echo "Robin MCP URL:      $ROBIN_MCP_BASE_URL"
echo ""
echo "Start the full stack with:"
echo "  $STACK_START_SCRIPT"
echo ""
echo "To configure WhatsApp or Codex again later:"
echo "  openclaw channels login --channel whatsapp"
echo "  openclaw models auth login --provider openai-codex"
