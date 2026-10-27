@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%" || exit /b 1

if not exist ".env" (
    echo Missing .env. Copy .env.example to .env and fill in your configuration.
    goto :error
)

if not exist ".venv\Scripts\python.exe" (
    echo Missing Python environment. Run: py -3.12 -m venv .venv
    echo Then run: .venv\Scripts\python.exe -m pip install -e .
    goto :error
)

".venv\Scripts\python.exe" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Backend dependencies are missing. Run: .venv\Scripts\python.exe -m pip install -e .
    goto :error
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo Node.js/npm was not found in PATH. Install Node.js first.
    goto :error
)

if not exist "frontend\node_modules\.bin\vite.cmd" (
    echo Frontend dependencies are missing. Run: cd frontend ^&^& npm install
    goto :error
)

if /I "%~1"=="--check" (
    echo All launch prerequisites are present.
    exit /b 0
)

start "Data Analysis Assistant API" /D "%ROOT%" "%ComSpec%" /k .venv\Scripts\python.exe -m uvicorn api.server:app --host 127.0.0.1 --port 8000
start "Data Analysis Assistant Web" /D "%ROOT%frontend" "%ComSpec%" /k npm.cmd run dev -- --host 127.0.0.1

echo Backend: http://127.0.0.1:8000/
echo Frontend: http://127.0.0.1:5173/
echo Close the API and Web windows to stop both services.
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5173/"
exit /b 0

:error
if /I not "%~1"=="--check" pause
exit /b 1
