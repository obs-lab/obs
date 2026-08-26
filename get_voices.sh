#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VOICE_DIR="${OBS_PIPER_DIR:-backend/models/piper}"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"

echo ""
echo "OBS-LAB - neural voices for speech synthesis"
echo ""

if ! command -v piper &>/dev/null && [ -z "$OBS_PIPER_BIN" ]; then
  echo "The piper binary was not found."
  echo "Install it inside the OBS virtual environment with:"
  echo "   source venv/bin/activate"
  echo "   pip install piper-tts"
  echo ""
  echo "The voices will still be downloaded now."
  echo ""
fi

if command -v curl &>/dev/null; then
  FETCH="curl -fL --progress-bar -o"
elif command -v wget &>/dev/null; then
  FETCH="wget -q --show-progress -O"
else
  echo "ERROR: neither curl nor wget was found."
  exit 1
fi

mkdir -p "$VOICE_DIR"

get_voice () {
  local path="$1"
  local name="$2"
  if [ -f "$VOICE_DIR/$name.onnx" ]; then
    echo "  already present: $name"
    return
  fi
  echo "  downloading $name"
  $FETCH "$VOICE_DIR/$name.onnx" "$BASE/$path/$name.onnx"
  $FETCH "$VOICE_DIR/$name.onnx.json" "$BASE/$path/$name.onnx.json"
}

echo "Italian:"
get_voice "it/it_IT/paola/medium" "it_IT-paola-medium"

echo ""
echo "English:"
get_voice "en/en_US/lessac/medium" "en_US-lessac-medium"

echo ""
echo "Voices installed in $SCRIPT_DIR/$VOICE_DIR"
echo ""
echo "OBS picks the voice by the language of the answer, and prefers the highest"
echo "quality model available for that language. Restart the backend to pick them up."
echo ""
echo "To add another language, browse https://huggingface.co/rhasspy/piper-voices"
echo "and drop the .onnx and .onnx.json files into the same folder. Keep the original"
echo "file names: OBS reads the language and the quality from them."
echo ""
