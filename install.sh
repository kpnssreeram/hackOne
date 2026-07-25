#!/usr/bin/env bash
set -e
export PATH="/opt/homebrew/bin:$PATH"

ROOT=$(cd "$(dirname "$0")" && pwd)
echo "=== NOLAN: Installing dependencies ==="

# Backend
cd "$ROOT/backend"
echo "→ Installing Python dependencies..."
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
echo "✓ Backend ready"

# Frontend
cd "$ROOT/frontend"
echo "→ Installing Node dependencies..."
npm install --legacy-peer-deps
echo "✓ Frontend ready"

echo ""
echo "=== Run: ./start.sh ==="
