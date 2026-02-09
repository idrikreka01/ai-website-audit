#!/bin/bash
# Docker wrapper script for running the ecommerce navigator
# Usage: ./run_nav_docker.sh <url> [viewport]

set -e

URL="${1:-}"
VIEWPORT="${2:-desktop}"

if [ -z "$URL" ]; then
    echo "Usage: ./run_nav_docker.sh <url> [viewport]"
    echo "Example: ./run_nav_docker.sh https://example.com desktop"
    exit 1
fi

# Load .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Set defaults if not in .env
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-ai_website_audit}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "Running navigator for: $URL (viewport: $VIEWPORT)"
echo "Make sure Docker services are running: docker-compose up -d postgres redis"
echo ""

docker-compose run --rm \
    -e DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}" \
    -e REDIS_URL="redis://redis:6379/0" \
    -e STORAGE_ROOT="/app/storage" \
    -e ARTIFACTS_DIR="/app/artifacts" \
    -e LOG_LEVEL="${LOG_LEVEL}" \
    worker \
    python run_nav.py --url "$URL" --viewport "$VIEWPORT"
