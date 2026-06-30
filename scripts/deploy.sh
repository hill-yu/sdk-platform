#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Building frontend..."
cd "${ROOT_DIR}/frontend"
npm install
npm run build

echo "Running backend tests..."
cd "${ROOT_DIR}"
python -m pytest backend/tests -q

echo "Deployment artifacts are ready."
