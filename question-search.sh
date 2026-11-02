#!/usr/bin/env bash
set -euo pipefail
module_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --directory "$module_dir" --frozen question-search "$@"
