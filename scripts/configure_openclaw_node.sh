#!/usr/bin/env sh
# Configure OpenClaw + Robin MCP on a compute node (Linux/macOS).
# Usage:
#   ./configure_openclaw_node.sh /path/to/openclaw-deploy-YYYYMMDD-HHMMSS.tar.gz
#   OPENCLAW_CRON_EXPR="0 7 * * *" OPENCLAW_CRON_MESSAGE="Morning brief" \
#     ./configure_openclaw_node.sh /path/to/bundle.tar.gz /opt/openclaw

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

if [ ! -f "$BUNDLE_PATH" ]; then
  echo "Bundle file not found: $BUNDLE_PATH" >&2
  exit 1
fi

require_cmd tar
require_cmd "$PYTHON_EXE"

MIN_NODE_MAJOR=22
install_or_upgrade_node() {
  current_major=0
  if command -v node >/dev/null 2>&1; then
    current_major=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)
  fi
  if [ "$current_major" -lt "$MIN_NODE_MAJOR" ] 2>/dev/null; then
    echo "Node.js v${MIN_NODE_MAJOR}+ required (current: ${current_major:-none}). Installing..."
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
    echo "Node.js v${current_major} OK (>= ${MIN_NODE_MAJOR})."
  fi
}

install_or_upgrade_node
require_cmd npm

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
WORKSPACE_SKILLS_DIR="$OPENCLAW_WORKSPACE/skills"
WORKSPACE_CONFIG_DIR="$OPENCLAW_WORKSPACE/config"
ROBIN_MCP_BASE_URL="http://$ROBIN_MCP_HOST:$ROBIN_MCP_PORT$ROBIN_MCP_PATH"

if [ ! -d "$ROBIN_ROOT" ]; then
  echo "Expected robin folder not found at $ROBIN_ROOT" >&2
  exit 1
fi
if [ ! -d "$SKILLS_SRC" ]; then
  echo "Expected skills folder not found at $SKILLS_SRC" >&2
  exit 1
fi

VENV_PATH="$ROBIN_ROOT/.venv"
echo "Creating Robin MCP virtual environment..."
"$PYTHON_EXE" -m venv "$VENV_PATH"

VENV_PYTHON="$VENV_PATH/bin/python"
echo "Installing Robin MCP Python dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROBIN_ROOT/requirements.txt"

if [ -d "$WORKSPACE_SKILLS_DIR" ]; then
  workspace_backup="$WORKSPACE_SKILLS_DIR.bak.$(date +%Y%m%d-%H%M%S)"
  echo "Backing up existing OpenClaw workspace skills to $workspace_backup"
  mv "$WORKSPACE_SKILLS_DIR" "$workspace_backup"
fi
echo "Moving bundled skills into OpenClaw workspace..."
mv "$SKILLS_SRC" "$WORKSPACE_SKILLS_DIR"

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

echo ""
echo "=== Setup: WhatsApp and Codex OAuth ==="
if [ "$RUN_WHATSAPP_LOGIN" = "1" ]; then
  echo "Link your WhatsApp account (QR or pairing)..."
  openclaw channels login --channel whatsapp </dev/tty || echo "WhatsApp login skipped (no tty or cancelled). Run manually: openclaw channels login --channel whatsapp"
fi
if [ "$RUN_CODEX_OAUTH" = "1" ]; then
  echo "Sign in with OpenAI Codex (browser OAuth)..."
  openclaw models auth login --provider openai-codex </dev/tty || echo "Codex OAuth skipped (no tty or cancelled). Run manually: openclaw models auth login --provider openai-codex"
fi

echo ""
echo "OpenClaw deployment configured."
echo "Bundle root:        $BUNDLE_ROOT"
echo "Robin root:         $ROBIN_ROOT"
echo "OpenClaw workspace: $OPENCLAW_WORKSPACE"
echo "Skills dir:         $WORKSPACE_SKILLS_DIR"
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
