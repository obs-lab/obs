chmod +x "$0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   OBS-LAB                                    ║"
echo "║   v2.6.0                                     ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

if command -v python3.11 &>/dev/null; then
  PYTHON=python3.11
elif command -v python3 &>/dev/null; then
  VER=$(python3 -c "import sys; print(sys.version_info.minor)")
  if [ "$VER" -le "11" ]; then
    PYTHON=python3
  else
    echo "ERRORE: Python 3.11 richiesto. Installa con: brew install python@3.11"
    exit 1
  fi
else
  echo "ERRORE: Python non trovato. Installa Python 3.11 da https://python.org"
  exit 1
fi

echo "Usando: $($PYTHON --version)"

if [ -d "venv" ]; then
  VENV_VER=$(venv/bin/python3 -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
  if [ "$VENV_VER" -gt "11" ]; then
    echo "Venv con Python incompatibile rilevato, ricicreazione..."
    rm -rf venv
  fi
fi

if [ ! -d "venv" ]; then
  echo "Creazione ambiente virtuale con Python 3.11..."
  $PYTHON -m venv venv
fi

source venv/bin/activate

echo "Installazione dipendenze (solo al primo avvio)..."
pip install -q -r requirements.txt

echo "Verifica del modello di embedding (scaricato solo al primo avvio)..."
python download_model.py
if [ $? -ne 0 ]; then
  echo ""
  echo "ERRORE: il modello di embedding non e' stato scaricato correttamente."
  echo "   Controlla la connessione e riprova con: python download_model.py"
  echo "   L'avvio e' stato interrotto per evitare un errore nel server."
  exit 1
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "ATTENZIONE: ANTHROPIC_API_KEY non impostata."
  echo "   Il sistema funzionera in modalita offline (senza LLM Claude)."
  echo "   Per abilitare Claude: export ANTHROPIC_API_KEY=sk-ant-..."
  echo ""
fi

echo "Avvio OBS-LAB su http://localhost:8000"
echo "   (Ctrl+C per fermare)"
echo ""

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload