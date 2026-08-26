#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "OBS-LAB - PRODUCTION"
echo "v2.6.0"
echo ""

if command -v python3.11 &>/dev/null; then
  PYTHON=python3.11
elif command -v python3 &>/dev/null; then
  VER=$(python3 -c "import sys; print(sys.version_info.minor)")
  if [ "$VER" -le "11" ]; then
    PYTHON=python3
  else
    echo "ERROR: Python 3.11 is required. Install it with: brew install python@3.11"
    exit 1
  fi
else
  echo "ERROR: Python not found. Install Python 3.11 from https://python.org"
  exit 1
fi

echo "Using: $($PYTHON --version)"

if [ -d "venv" ]; then
  VENV_VER=$(venv/bin/python3 -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
  if [ "$VENV_VER" -gt "11" ]; then
    echo "Incompatible Python detected in venv, recreating..."
    rm -rf venv
  fi
fi

if [ ! -d "venv" ]; then
  echo "Creating virtual environment with Python 3.11..."
  $PYTHON -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo "Checking embedding model (downloaded only on first start)..."
python download_model.py
if [ $? -ne 0 ]; then
  echo ""
  echo "ERROR: the embedding model was not downloaded correctly."
  echo "   Check your connection and retry with: python download_model.py"
  echo "   Startup was stopped to avoid a server error."
  exit 1
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "NOTE: no cloud LLM key set. Running in offline mode."
  echo "   To enable the cloud LLM: export ANTHROPIC_API_KEY=your-key"
  echo ""
fi

OBS_HOST="${OBS_HOST:-0.0.0.0}"
OBS_PORT="${OBS_PORT:-8000}"
OBS_TIMEOUT="${OBS_TIMEOUT:-1800}"
OBS_SSL_CERT="${OBS_SSL_CERT:-}"
OBS_SSL_KEY="${OBS_SSL_KEY:-}"

OBS_SCHEME=http
SSL_ARGS=()
if [ -n "$OBS_SSL_CERT" ] && [ -n "$OBS_SSL_KEY" ]; then
  if [ -f "$OBS_SSL_CERT" ] && [ -f "$OBS_SSL_KEY" ]; then
    SSL_ARGS=(--ssl-certfile "$OBS_SSL_CERT" --ssl-keyfile "$OBS_SSL_KEY")
    OBS_SCHEME=https
  else
    echo "WARNING: OBS_SSL_CERT or OBS_SSL_KEY point to a missing file. Falling back to http."
    echo "   Microphone capture will not work outside localhost."
    echo ""
  fi
elif [ "$OBS_HOST" != "127.0.0.1" ] && [ "$OBS_HOST" != "localhost" ]; then
  echo "NOTE: serving over plain http on a network address."
  echo "   Browsers only grant microphone access on localhost or over https."
  echo "   To enable voice for remote users set OBS_SSL_CERT and OBS_SSL_KEY."
  echo ""
fi


export OBS_ENV=production

echo "Starting OBS-LAB in production on $OBS_SCHEME://$OBS_HOST:$OBS_PORT"
echo "   single worker, keep-alive ${OBS_TIMEOUT}s"
echo "   (Ctrl+C to stop)"
echo ""

cd backend
uvicorn main:app \
  --host "$OBS_HOST" \
  --port "$OBS_PORT" \
  --workers 1 \
  --timeout-keep-alive "$OBS_TIMEOUT" \
  --limit-concurrency 64 \
  --no-access-log \
  "${SSL_ARGS[@]}"
