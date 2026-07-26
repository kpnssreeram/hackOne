#!/usr/bin/env bash
export PATH="/opt/homebrew/bin:$PATH"

ROOT=$(cd "$(dirname "$0")" && pwd)

if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
  echo "Backend dependencies are not installed yet. Run ./install.sh first."
  exit 1
fi

# Nolan needs both ports. Stopping only the Next.js port leaves an old backend
# serving stale code, which is especially confusing after a voice-pipeline fix.
if command -v lsof >/dev/null 2>&1; then
  for PORT in 8000 3000; do
    if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "Port $PORT is already in use. Stop the existing Nolan process, then run ./start.sh again."
      echo "Tip: lsof -ti :3000,:8000 | xargs kill"
      exit 1
    fi
  done
fi

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
"$ROOT/backend/.venv/bin/python" -m uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
echo "✓ Backend: http://localhost:8000"

# Frontend
cd "$ROOT/frontend"
if command -v npm >/dev/null 2>&1; then
  npm run dev &
elif command -v pnpm >/dev/null 2>&1; then
  pnpm run dev &
else
  echo "Node package manager not found. Install Node.js, then run ./install.sh."
  kill "$BACKEND_PID" 2>/dev/null || true
  exit 1
fi
FRONTEND_PID=$!
echo "✓ Frontend: http://localhost:3000"

echo ""
echo "  Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" SIGINT SIGTERM
wait
