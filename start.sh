#!/bin/bash

set -e

echo "🚀 Starting F1 Chatter..."

# Load environment variables if .env exists
if [ -f ".env" ]; then
    echo "🔐 Loading environment variables from .env"
    set -a
    # shellcheck disable=SC1091
    source ".env"
    set +a
else
    echo "⚠️  Warning: .env file not found. Ensure DISCORD_OAUTH_TOKEN and other secrets are set."
fi

# Ensure required CLI tooling is available
if ! command -v curl &> /dev/null; then
    echo "❌ Error: curl is required but not found. Please install curl."
    exit 1
fi

if ! command -v unzip &> /dev/null; then
    echo "❌ Error: unzip is required but not found. Please install unzip."
    exit 1
fi

DISCORD_EXPORTER_DIR="discord_msg_fetcher"
DISCORD_EXPORTER_BIN="${DISCORD_EXPORTER_DIR}/DiscordChatExporter.Cli"
DISCORD_EXPORTER_URL="https://github.com/Tyrrrz/DiscordChatExporter/releases/latest/download/DiscordChatExporter.Cli.osx-arm64.zip"

if [ ! -f "${DISCORD_EXPORTER_BIN}" ]; then
    echo "⬇️  Installing DiscordChatExporter CLI..."
    mkdir -p "${DISCORD_EXPORTER_DIR}"
    TEMP_ZIP="${DISCORD_EXPORTER_DIR}/DiscordChatExporter.Cli.zip"
    curl -L -o "${TEMP_ZIP}" "${DISCORD_EXPORTER_URL}"
    unzip -o "${TEMP_ZIP}" -d "${DISCORD_EXPORTER_DIR}" >/dev/null
    rm -f "${TEMP_ZIP}"
    chmod +x "${DISCORD_EXPORTER_BIN}"
    echo "✅ DiscordChatExporter CLI installed."
else
    echo "✅ DiscordChatExporter CLI found at ${DISCORD_EXPORTER_BIN}"
fi

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is required but not found. Please install uv first."
    echo "   Visit: https://github.com/astral-sh/uv"
    exit 1
fi

echo "✅ uv found"

# Force unbuffered stdout/stderr for Python processes so logs flush immediately.
export PYTHONUNBUFFERED=1

# Sync dependencies
echo "📦 Syncing dependencies..."
uv sync

# Run migrations
echo "🗄️  Running database migrations..."
uv run python manage.py migrate

# Start live polling loop in the background
POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS:-30}

start_polling_loop() {
    echo "🔁 Starting live message poller (interval ${POLL_INTERVAL_SECONDS}s)..."
    while true; do
        timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "⏱️  [$timestamp] Polling recent messages..."
        if ! uv run python manage.py poll_recent_messages --window-seconds "${POLL_INTERVAL_SECONDS}"; then
            poll_exit=$?
            echo "⚠️  Polling command failed with exit code ${poll_exit}. Retrying after sleep."
        fi
        sleep "${POLL_INTERVAL_SECONDS}"
    done
}

start_polling_loop &
POLL_PID=$!

cleanup() {
    echo "🛑 Stopping live message poller..."
    if [ -n "${POLL_PID}" ] && kill -0 "${POLL_PID}" 2>/dev/null; then
        kill "${POLL_PID}" 2>/dev/null || true
        wait "${POLL_PID}" 2>/dev/null || true
    fi
}

trap cleanup INT TERM EXIT

# Start Django backend with gunicorn
echo "🌐 Starting Django backend on http://localhost:8000..."
echo "   API available at: http://localhost:8000/api/"
echo "   API docs available at: http://localhost:8000/api/docs"
echo ""
uv run gunicorn \
    f1_chatter.wsgi:application \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --reload \
    --log-level info \
    --error-logfile - \
    --access-logfile - \
    --capture-output
gunicorn_exit=$?

# Ensure the poller is stopped when gunicorn exits
cleanup

exit "${gunicorn_exit}"

