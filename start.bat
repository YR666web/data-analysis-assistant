@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%" || exit /b 1
echo Project directory: %ROOT%

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

set "API_PORT="
for %%P in (8000 8001 8002 8003 8004 8005 8006) do (
    if not defined API_PORT (
        powershell -NoProfile -Command "try { $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, %%P); $listener.Start(); $listener.Stop(); exit 0 } catch { exit 1 }" >nul 2>&1
        if not errorlevel 1 set "API_PORT=%%P"
    )
)
if not defined API_PORT (
    echo No backend port is available between 8000 and 8006.
    goto :error
)

set "WEB_PORT="
for %%P in (5173 5174 5175 5176 5177 5178 5179 5180) do (
    if not defined WEB_PORT (
        powershell -NoProfile -Command "try { $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, %%P); $listener.Start(); $listener.Stop(); exit 0 } catch { exit 1 }" >nul 2>&1
        if not errorlevel 1 set "WEB_PORT=%%P"
    )
)
if not defined WEB_PORT (
    echo No frontend port is available between 5173 and 5180.
    goto :error
)

if /I "%~1"=="--check" (
    echo All launch prerequisites are present. Backend port: %API_PORT%. Frontend port: %WEB_PORT%.
    exit /b 0
)

set "DATA_ANALYSIS_API_URL=http://127.0.0.1:%API_PORT%"
start "Data Analysis Assistant API" /D "%ROOT%" "%ComSpec%" /k .venv\Scripts\python.exe -m uvicorn api.server:app --host 127.0.0.1 --port %API_PORT%
start "Data Analysis Assistant Web" /D "%ROOT%frontend" "%ComSpec%" /k npm.cmd run dev -- --host 127.0.0.1 --port %WEB_PORT% --strictPort

echo Backend: http://127.0.0.1:%API_PORT%/
echo Frontend: http://127.0.0.1:%WEB_PORT%/
echo Close the API and Web windows to stop both services.
echo Waiting for this project's frontend...
powershell -NoProfile -Command "$expected = [regex]::Match([IO.File]::ReadAllText('frontend\index.html'), '<title>(.*?)</title>').Groups[1].Value; for ($i = 0; $i -lt 30; $i++) { try { $page = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%WEB_PORT%/' -TimeoutSec 2; if ($page.Content.Contains($expected)) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1" >nul 2>&1
if errorlevel 1 (
    echo Frontend did not start at port %WEB_PORT%. Check the Web window for details.
    goto :error
)
start "" "http://127.0.0.1:%WEB_PORT%/"
exit /b 0

:error
if /I not "%~1"=="--check" pause
exit /b 1
