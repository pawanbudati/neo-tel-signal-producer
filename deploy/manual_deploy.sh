#!/usr/bin/env bash
set -Eeuo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Manual Deployment Script for Signal Producer
# Matches GitHub Actions (.github/workflows/deploy.yml)
# Usage:
#   ./deploy/manual_deploy.sh [--skip-kafka]
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load configuration file if present
for env_file in "$ROOT_DIR/.env.deploy" "$SCRIPT_DIR/.env.deploy" "$ROOT_DIR/.deploy.env" "$SCRIPT_DIR/deploy.env"; do
  if [[ -f "$env_file" ]]; then
    echo "Loading deployment config from $env_file"
    # shellcheck disable=SC1090
    set -a
    source "$env_file"
    set +a
    break
  fi
done

SKIP_KAFKA="${SKIP_KAFKA:-false}"
for arg in "$@"; do
  if [[ "$arg" == "--skip-kafka" ]]; then
    SKIP_KAFKA="true"
  fi
done

HOST="${GCP_VM_HOST:-${VM_HOST:-}}"
USER="${GCP_VM_USER:-${VM_USER:-}}"
KEY="${GCP_VM_SSH_KEY:-${SSH_KEY_PATH:-}}"
PORT="${GCP_VM_SSH_PORT:-${VM_PORT:-22}}"
REMOTE_PATH="${PRODUCER_DEPLOY_PATH:-${DEPLOY_PATH:-}}"
ADVERTISED_HOST="${KAFKA_ADVERTISED_HOST:-}"

if [[ -z "$HOST" || -z "$USER" ]]; then
  echo "Error: GCP_VM_HOST and GCP_VM_USER must be set in .env.deploy or environment." >&2
  exit 1
fi

if [[ -z "$REMOTE_PATH" || "$REMOTE_PATH" == "/home/" ]]; then
  REMOTE_PATH="/home/$USER/apps/neo-tel-signal-producer"
fi

SSH_OPTS=(-p "$PORT" -o "StrictHostKeyChecking=accept-new")
if [[ -n "$KEY" && -f "$KEY" ]]; then
  SSH_OPTS+=(-i "$KEY")
fi

echo "================================================================="
echo ">>> Deploying Producer to $USER@$HOST:$PORT"
echo ">>> Remote Path: $REMOTE_PATH"
echo ">>> Skip Kafka Container: $SKIP_KAFKA"
echo "================================================================="

# 1. Ensure target directory exists on remote VM
ssh "${SSH_OPTS[@]}" "$USER@$HOST" "mkdir -p '$REMOTE_PATH'"

# 2. Sync repository files (excluding git, venv, sessions, secrets, logs)
echo ">>> Syncing repository files to $USER@$HOST..."
if command -v rsync >/dev/null 2>&1; then
  RSYNC_SSH="ssh -p $PORT -o StrictHostKeyChecking=accept-new"
  if [[ -n "$KEY" && -f "$KEY" ]]; then
    RSYNC_SSH="$RSYNC_SSH -i $KEY"
  fi

  rsync -az --delete \
    --exclude='.git/' \
    --exclude='.env' --include='.env.example' --exclude='.env.*' \
    --exclude='.venv/' --exclude='venv/' \
    --exclude='*.session' --exclude='*.session-*' \
    --exclude='logs/' --exclude='*.log' \
    --exclude='__pycache__/' \
    -e "$RSYNC_SSH" \
    "$ROOT_DIR/" "$USER@$HOST:$REMOTE_PATH/"
else
  echo ">>> rsync not found locally; streaming via tar over ssh..."
  tar --exclude=".git" \
      --exclude=".env" \
      --exclude=".env.*" \
      --exclude=".venv" \
      --exclude="venv" \
      --exclude="*.session" \
      --exclude="*.session-*" \
      --exclude="logs" \
      --exclude="*.log" \
      --exclude="__pycache__" \
      -C "$ROOT_DIR" -czf - . | ssh "${SSH_OPTS[@]}" "$USER@$HOST" "tar -xzf - -C '$REMOTE_PATH'"
fi

# 3. Ensure Kafka container is running if not skipped
if [[ "$SKIP_KAFKA" != "true" ]]; then
  echo ">>> Ensuring Kafka container is running on $HOST..."
  ssh "${SSH_OPTS[@]}" "$USER@$HOST" \
    "DEPLOY_PATH='$REMOTE_PATH' KAFKA_ADVERTISED_HOST='$ADVERTISED_HOST' bash '$REMOTE_PATH/deploy/ensure-kafka.sh'"
else
  echo ">>> Skipping Kafka container management on $HOST (--skip-kafka requested)."
fi

# 4. Execute remote deploy.sh
echo ">>> Executing remote deploy.sh on $HOST..."
ssh "${SSH_OPTS[@]}" "$USER@$HOST" \
  "DEPLOY_PATH='$REMOTE_PATH' bash '$REMOTE_PATH/deploy/deploy.sh'"

echo ">>> Producer deployment completed successfully!"
