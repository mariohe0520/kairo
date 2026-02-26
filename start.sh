#!/bin/bash
# Kairo AI — Quick Start
# Usage: ./start.sh

set -e

echo "🎬 Starting Kairo AI..."

# Check Python deps
pip3 install -q fastapi uvicorn python-multipart websockets numpy 2>/dev/null || true

# Check Node deps
if [ ! -d "node_modules" ]; then
  echo "Installing Node dependencies..."
  npm install
fi

# Start the Python server in background
echo "Starting AI backend on port 8420..."
python3 -m uvicorn server:app --host 127.0.0.1 --port 8420 &
SERVER_PID=$!

# Wait for server
for i in {1..10}; do
  if curl -s http://127.0.0.1:8420/api/health > /dev/null 2>&1; then
    echo "Backend ready!"
    break
  fi
  sleep 1
done

# Start Electron
echo "Launching Kairo UI..."
npx electron . 2>/dev/null

# Cleanup
kill $SERVER_PID 2>/dev/null
echo "Kairo stopped."
