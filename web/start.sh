#!/usr/bin/env bash
# Start the question-bank web UI with env vars from a local env file.
# Override the env file with QUESTION_BANK_ENV_FILE (default: .env next to this script).
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${QUESTION_BANK_ENV_FILE:-$(dirname "$0")/../.env}"
exec uv run --extra web --env-file "$ENV_FILE" python web/server.py "$@"
