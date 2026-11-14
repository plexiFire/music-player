#!/usr/bin/env bash
# Start Senora's page with one command:   ./run.sh
#   ./run.sh --port 8002      use another port
#   ./run.sh --no-browser     do not open the browser
#   ./run.sh --dev            restart by itself when the code changes (for development only: a restart stops a build that is running)
set -e
cd "$(dirname "$0")"

PORT=8001; OPEN=1; DEV=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-browser) OPEN=0; shift ;;
    --dev) DEV=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try ./run.sh --help)"; exit 2 ;;
  esac
done

# 1. a Python with our packages: this folder's .venv, else the one used so far, else a new .venv
PY=""
for CAND in "./.venv/bin/python" "$HOME/Desktop/senora/senora/.venv/bin/python"; do
  if [ -x "$CAND" ]; then PY="$CAND"; break; fi
done
if [ -z "$PY" ]; then
  echo "First run: making a Python environment in .venv ..."
  python3 -m venv .venv
  PY="./.venv/bin/python"
fi

# 2. ffmpeg is needed for everything audio and video
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is not installed. Install it once with:  brew install ffmpeg"
  exit 1
fi

# 3. packages (only installs when something is missing)
if ! "$PY" -c "import fastapi, uvicorn, PIL, numpy, yt_dlp, mutagen, requests, multipart" >/dev/null 2>&1; then
  echo "Installing the packages (first run only, about a minute) ..."
  "$PY" -m pip install -q -r requirements.txt
fi

# 4. an older Senora page on the same port is stopped first (only Senora's own, never another program)
pkill -f "uvicorn server.app:app --port $PORT" >/dev/null 2>&1 && sleep 1 || true
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is used by another program. Try:  ./run.sh --port 8002"
  exit 1
fi

echo "Senora is starting at  http://localhost:$PORT   (press Ctrl+C to stop; everything you did is saved as you go)"
if [ "$OPEN" = "1" ]; then
  ( sleep 2; open "http://localhost:$PORT" >/dev/null 2>&1 || true ) &
fi
if [ "$DEV" = "1" ]; then
  exec "$PY" -m uvicorn server.app:app --port "$PORT" --reload --reload-dir server --reload-dir engine
fi
exec "$PY" -m uvicorn server.app:app --port "$PORT"
