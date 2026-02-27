#!/bin/bash
# Kairo AI — Quick Start (Web UI)
# Usage: ./start.sh
#
# Starts the FastAPI backend which also serves the web UI.
# Open http://localhost:8420 in your browser.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ╔═══════════════════════════════════╗"
echo "  ║        KAIRO AI Clip Editor       ║"
echo "  ║   AI-Powered Video Intelligence   ║"
echo "  ╚═══════════════════════════════════╝"
echo ""

# Check Python deps
echo "[1/3] Checking Python dependencies..."
pip3 install -q fastapi uvicorn python-multipart websockets numpy 2>/dev/null || true

# Verify web UI exists
if [ ! -f "web/index.html" ]; then
  echo "ERROR: Web UI not found at web/index.html"
  echo "Please ensure the web/ directory exists with index.html, style.css, and app.js"
  exit 1
fi
echo "[2/3] Web UI found at web/"

# Start the Python server (serves both API and web UI)
echo "[3/3] Starting server on http://localhost:8420 ..."
echo ""

python3 -m uvicorn server:app --host 127.0.0.1 --port 8420 --reload &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for backend..."
for i in {1..15}; do
  if curl -s http://127.0.0.1:8420/api/health > /dev/null 2>&1; then
    echo ""
    echo "  Server ready!"
    echo ""
    echo "  Web UI:  http://localhost:8420"
    echo "  API:     http://localhost:8420/api/health"
    echo "  Docs:    http://localhost:8420/docs"
    echo ""
    echo "  Press Ctrl+C to stop."
    echo ""
    break
  fi
  sleep 1
done

# Try to open browser
if command -v open &> /dev/null; then
  open "http://localhost:8420" 2>/dev/null || true
elif command -v xdg-open &> /dev/null; then
  xdg-open "http://localhost:8420" 2>/dev/null || true
fi

# Wait for server process
trap "kill $SERVER_PID 2>/dev/null; echo ''; echo 'Kairo stopped.'; exit 0" INT TERM
wait $SERVER_PID
