#!/usr/bin/env bash
# Start the question-bank web UI with the same OpenRouter key the Study profile uses.
# Override the env file with QUESTION_BANK_ENV_FILE. The module itself stays env-only.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${QUESTION_BANK_ENV_FILE:-$HOME/.hermes/profiles/study/.env}"
exec uv run --extra web --env-file "$ENV_FILE" python web/server.py "$@"
