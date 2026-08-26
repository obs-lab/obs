@echo off

echo.
echo OBS-LAB - PRODUCTION
echo v2.6.0
echo.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python not found. Install Python 3.10+ from https://python.org
  pause
  exit /b
)

if not exist "venv" (
  echo Creating virtual environment...
  python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt

echo Checking embedding model (downloaded only on first start)...
python download_model.py
if errorlevel 1 (
  echo.
  echo ERROR: the embedding model was not downloaded correctly.
  echo Check your connection and retry with: python download_model.py
  echo Startup was stopped to avoid a server error.
  pause
  exit /b
)

if "%ANTHROPIC_API_KEY%"=="" (
  echo.
  echo NOTE: no cloud LLM key set. Running in offline mode.
  echo To enable the cloud LLM: set ANTHROPIC_API_KEY=your-key
  echo.
)

if "%OBS_HOST%"=="" set OBS_HOST=0.0.0.0
if "%OBS_PORT%"=="" set OBS_PORT=8000
if "%OBS_TIMEOUT%"=="" set OBS_TIMEOUT=1800
set OBS_ENV=production
set SSL_ARGS=
set OBS_SCHEME=http
if not "%OBS_SSL_CERT%"=="" if not "%OBS_SSL_KEY%"=="" (
  set SSL_ARGS=--ssl-certfile "%OBS_SSL_CERT%" --ssl-keyfile "%OBS_SSL_KEY%"
  set OBS_SCHEME=https
)
if "%OBS_SCHEME%"=="http" (
  echo NOTE: browsers only grant microphone access on localhost or over https.
  echo    To enable voice for remote users set OBS_SSL_CERT and OBS_SSL_KEY.
  echo.
)

echo Starting OBS-LAB in production on %OBS_SCHEME%://%OBS_HOST%:%OBS_PORT%
echo    single worker, keep-alive %OBS_TIMEOUT%s
echo    Press Ctrl+C to stop.
echo.

cd backend
uvicorn main:app --host %OBS_HOST% --port %OBS_PORT% --workers 1 --timeout-keep-alive %OBS_TIMEOUT% --limit-concurrency 64 --no-access-log %SSL_ARGS%
pause
