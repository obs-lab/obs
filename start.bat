@echo off

echo.
echo ╔══════════════════════════════════════════════╗
echo ║   OBS-LAB                                    ║
echo ║   v2.6.0                                     ║
echo ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo ERRORE: Python non trovato. Installa Python 3.10+ da https://python.org
  pause
  exit /b
)

if not exist "venv" (
  echo Creazione ambiente virtuale...
  python -m venv venv
)

call venv\Scripts\activate.bat

echo Installazione dipendenze...
pip install -q -r requirements.txt

echo Verifica del modello di embedding (scaricato solo al primo avvio)...
python download_model.py
if errorlevel 1 (
  echo.
  echo ERRORE: il modello di embedding non e' stato scaricato correttamente.
  echo Controlla la connessione e riprova con: python download_model.py
  echo L'avvio e' stato interrotto per evitare un errore nel server.
  pause
  exit /b
)

if "%ANTHROPIC_API_KEY%"=="" (
  echo.
  echo ATTENZIONE: ANTHROPIC_API_KEY non impostata.
  echo Il sistema funzionerà in modalità offline.
  echo Per abilitare Claude: set ANTHROPIC_API_KEY=sk-ant-...
  echo.
)

echo Avvio OBS-LAB su http://localhost:8000
echo Premi Ctrl+C per fermare.
echo.

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause