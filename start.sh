#!/usr/bin/env bash
export PATH="/opt/homebrew/bin:$PATH"

ROOT=$(cd "$(dirname "$0")" && pwd)

echo ""
echo "  ███╗   ██╗ ██████╗ ██╗      █████╗ ███╗   ██╗"
echo "  ████╗  ██║██╔═══██╗██║     ██╔══██╗████╗  ██║"
echo "  ██╔██╗ ██║██║   ██║██║     ███████║██╔██╗ ██║"
echo "  ██║╚██╗██║██║   ██║██║     ██╔══██║██║╚██╗██║"
echo "  ██║ ╚████║╚██████╔╝███████╗██║  ██║██║ ╚████║"
echo "  ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝"
echo ""
echo "  Imagination → Cinematic Audio"
echo "  Pocket FM × OpenAI — Zero to One"
echo ""

# Backend
cd "$ROOT/backend"
source .venv/bin/activate 2>/dev/null || true
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
echo "✓ Backend: http://localhost:8000"

# Frontend
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!
echo "✓ Frontend: http://localhost:3000"

echo ""
echo "  Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" SIGINT SIGTERM
wait
