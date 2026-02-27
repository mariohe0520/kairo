#!/bin/bash
# ============================================================
# Kairo AI Clip Editor — One-Click Launcher
# ============================================================
# Usage: ./start.sh
#
# Installs Python deps, validates system tools, starts the
# FastAPI backend + web UI, and opens your browser.
#
# After starting, open:  http://localhost:8420
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${KAIRO_PORT:-8420}"
HOST="${KAIRO_HOST:-127.0.0.1}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo ""
echo -e "${PURPLE}${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║                                          ║"
echo "  ║       KAIRO AI CLIP EDITOR               ║"
echo "  ║       AI-Powered Video Intelligence      ║"
echo "  ║                                          ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ----------------------------------------------------------
# Step 1: Check Python
# ----------------------------------------------------------
echo -e "${CYAN}[1/5]${NC} Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: Python 3 is required but not found.${NC}"
    echo "  Install it: brew install python3"
    exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "  ${GREEN}Python ${PY_VERSION} found${NC}"

# ----------------------------------------------------------
# Step 2: Install Python dependencies
# ----------------------------------------------------------
echo -e "${CYAN}[2/5]${NC} Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip3 install -q -r requirements.txt 2>&1 | tail -1 || {
        echo -e "${YELLOW}  Warning: Some packages failed to install. Trying core deps...${NC}"
        pip3 install -q fastapi "uvicorn[standard]" python-multipart websockets numpy 2>/dev/null || true
    }
    echo -e "  ${GREEN}Dependencies installed${NC}"
else
    pip3 install -q fastapi "uvicorn[standard]" python-multipart websockets numpy 2>/dev/null || true
    echo -e "  ${GREEN}Core dependencies installed${NC}"
fi

# ----------------------------------------------------------
# Step 3: Check system tools
# ----------------------------------------------------------
echo -e "${CYAN}[3/5]${NC} Checking system tools..."

WARNINGS=""

if command -v ffmpeg &> /dev/null; then
    FF_VERSION=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')
    echo -e "  ${GREEN}ffmpeg ${FF_VERSION} found${NC}"
else
    WARNINGS="${WARNINGS}\n  ${YELLOW}ffmpeg not found (needed for video processing)${NC}"
    WARNINGS="${WARNINGS}\n    Install: ${BOLD}brew install ffmpeg${NC}"
fi

if command -v yt-dlp &> /dev/null; then
    echo -e "  ${GREEN}yt-dlp found${NC}"
else
    WARNINGS="${WARNINGS}\n  ${YELLOW}yt-dlp not found (needed for URL downloads)${NC}"
    WARNINGS="${WARNINGS}\n    Install: ${BOLD}brew install yt-dlp${NC} or ${BOLD}pip3 install yt-dlp${NC}"
fi

if command -v whisper &> /dev/null; then
    echo -e "  ${GREEN}whisper found${NC}"
else
    WARNINGS="${WARNINGS}\n  ${YELLOW}whisper not found (needed for speech-to-text)${NC}"
    WARNINGS="${WARNINGS}\n    Install: ${BOLD}pip3 install openai-whisper${NC}"
fi

if [ -n "$WARNINGS" ]; then
    echo -e "\n  ${YELLOW}Optional tools missing (app will still work for local files):${NC}"
    echo -e "$WARNINGS"
    echo ""
fi

# Check for LLM API keys (optional, for AI highlight detection)
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo -e "  ${GREEN}Claude API key found (LLM highlights enabled)${NC}"
elif [ -n "${OPENAI_API_KEY:-}" ]; then
    echo -e "  ${GREEN}OpenAI API key found (LLM highlights enabled)${NC}"
else
    echo -e "  ${YELLOW}No LLM API key (highlight detection uses heuristics)${NC}"
    echo -e "    Set ${BOLD}ANTHROPIC_API_KEY${NC} or ${BOLD}OPENAI_API_KEY${NC} for AI-powered highlights"
fi

# ----------------------------------------------------------
# Step 4: Verify web UI
# ----------------------------------------------------------
echo -e "${CYAN}[4/5]${NC} Verifying web UI..."
if [ ! -f "web/index.html" ]; then
    echo -e "${RED}ERROR: Web UI not found at web/index.html${NC}"
    echo "  The web/ directory must contain index.html, style.css, and app.js"
    exit 1
fi
echo -e "  ${GREEN}Web UI found at web/${NC}"

# ----------------------------------------------------------
# Step 5: Start the server
# ----------------------------------------------------------
echo -e "${CYAN}[5/5]${NC} Starting Kairo server..."
echo ""

# Create output directory
mkdir -p output

# Kill any existing server on the port
if lsof -i :${PORT} -t &>/dev/null 2>&1; then
    echo -e "  ${YELLOW}Port ${PORT} is in use. Stopping existing process...${NC}"
    kill $(lsof -i :${PORT} -t) 2>/dev/null || true
    sleep 1
fi

# Start the server in background
python3 -m uvicorn server:app --host "$HOST" --port "$PORT" --reload --log-level info &
SERVER_PID=$!

# Trap Ctrl+C to clean up
cleanup() {
    echo ""
    echo -e "${CYAN}Shutting down Kairo...${NC}"
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    echo -e "${GREEN}Kairo stopped. Goodbye!${NC}"
    exit 0
}
trap cleanup INT TERM

# Wait for server to be ready
echo -e "  Waiting for server to start..."
READY=false
for i in {1..20}; do
    if curl -s "http://${HOST}:${PORT}/api/health" > /dev/null 2>&1; then
        READY=true
        break
    fi
    # Check if server process is still alive
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo -e "${RED}ERROR: Server failed to start. Check the logs above.${NC}"
        exit 1
    fi
    sleep 1
done

if [ "$READY" = true ]; then
    echo ""
    echo -e "${GREEN}${BOLD}  ================================================${NC}"
    echo -e "${GREEN}${BOLD}      Kairo is running!${NC}"
    echo -e "${GREEN}${BOLD}  ================================================${NC}"
    echo ""
    echo -e "  ${BOLD}Web UI:${NC}    ${CYAN}http://localhost:${PORT}${NC}"
    echo -e "  ${BOLD}API Docs:${NC}  ${CYAN}http://localhost:${PORT}/docs${NC}"
    echo -e "  ${BOLD}Health:${NC}    ${CYAN}http://localhost:${PORT}/api/health${NC}"
    echo ""
    echo -e "  ${BOLD}How to use:${NC}"
    echo -e "    1. Open ${CYAN}http://localhost:${PORT}${NC} in your browser"
    echo -e "    2. Paste a YouTube/Twitch URL or drag-drop a video file"
    echo -e "    3. Click ${PURPLE}\"Create Viral Clip\"${NC}"
    echo -e "    4. Watch the AI pipeline process your video"
    echo -e "    5. Download your finished clip"
    echo ""
    echo -e "  Press ${BOLD}Ctrl+C${NC} to stop the server."
    echo ""

    # Try to open browser
    if command -v open &> /dev/null; then
        open "http://localhost:${PORT}" 2>/dev/null || true
    elif command -v xdg-open &> /dev/null; then
        xdg-open "http://localhost:${PORT}" 2>/dev/null || true
    fi
else
    echo -e "${RED}WARNING: Server did not respond within 20 seconds.${NC}"
    echo -e "  It may still be starting. Try: ${CYAN}http://localhost:${PORT}${NC}"
    echo ""
fi

# Wait for server to run
wait $SERVER_PID
