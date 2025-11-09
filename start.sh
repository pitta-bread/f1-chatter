#!/bin/bash

set -e

echo "🚀 Starting F1 Chatter..."

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is required but not found. Please install uv first."
    echo "   Visit: https://github.com/astral-sh/uv"
    exit 1
fi

echo "✅ uv found"

# Sync dependencies
echo "📦 Syncing dependencies..."
uv sync

# Run migrations
echo "🗄️  Running database migrations..."
uv run python manage.py migrate

# Start Django backend with gunicorn
echo "🌐 Starting Django backend on http://localhost:8000..."
echo "   API available at: http://localhost:8000/api/"
echo "   API docs available at: http://localhost:8000/api/docs"
echo ""
uv run gunicorn f1_chatter.wsgi:application --bind 0.0.0.0:8000 --reload

