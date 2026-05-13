#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/official-doc-frontend"

VITE_DEV_PORT="${FRONTEND_PORT:-62233}" \
VITE_PROXY_TARGET="${VITE_PROXY_TARGET:-http://127.0.0.1:8009}" \
npm run dev
