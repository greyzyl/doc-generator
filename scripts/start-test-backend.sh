#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

python official_doc_flask_api.py --host "${BACKEND_HOST:-127.0.0.1}" --port "${BACKEND_PORT:-8010}"
