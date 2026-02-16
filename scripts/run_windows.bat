@echo off
REM ── Freecord: Windows Run Script ──

echo ========================================
echo   Freecord - Starting all services
echo ========================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

REM ── Check prerequisites ──

echo [1/7] Checking prerequisites...

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python is not installed.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

where cargo >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Rust/Cargo is not installed.
    echo Download from: https://www.rust-lang.org/tools/install
    pause
    exit /b 1
)
cargo --version

REM ── Set environment variables ──

echo [2/7] Setting environment variables...

if not defined MASTER_SECRET set "MASTER_SECRET=my-super-secret-master-key-change-me"
if not defined RUST_LOG set "RUST_LOG=info"
if not defined JWT_SECRET set "JWT_SECRET=change-this-jwt-secret-key"
if not defined RUST_SERVICE_URL set "RUST_SERVICE_URL=http://127.0.0.1:8001"
if not defined FLASK_SECRET set "FLASK_SECRET=change-this-flask-secret"
if not defined API_URL set "API_URL=http://127.0.0.1:8000"

REM ── Build Rust encryption service ──

echo [3/7] Building Rust encryption service...
cd /d "%PROJECT_DIR%\rust_encryption_service"
cargo build --release

echo [4/7] Starting Rust encryption service on port 8001...
start "Freecord-Rust" cmd /c "cargo run --release"

echo   Waiting for Rust service...
timeout /t 10 /nobreak >nul

REM ── Set up FastAPI backend ──

echo [5/7] Setting up FastAPI backend...
cd /d "%PROJECT_DIR%\backend_fastapi"

if not exist "venv" (
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo   Starting FastAPI backend on port 8000...
start "Freecord-FastAPI" cmd /c "venv\Scripts\activate.bat && python -m uvicorn main:app --host 127.0.0.1 --port 8000"
call deactivate

timeout /t 5 /nobreak >nul

REM ── Set up Flask frontend ──

echo [6/7] Setting up Flask frontend...
cd /d "%PROJECT_DIR%\frontend_flask"

if not exist "venv" (
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo   Starting Flask frontend on port 5000...
start "Freecord-Flask" cmd /c "venv\Scripts\activate.bat && python app.py"
call deactivate

timeout /t 3 /nobreak >nul

REM ── Open browser ──

echo [7/7] Opening browser...
start http://127.0.0.1:5000

echo.
echo ========================================
echo   All services are running!
echo.
echo   Frontend:    http://127.0.0.1:5000
echo   Backend API: http://127.0.0.1:8000
echo   Encryption:  http://127.0.0.1:8001
echo.
echo   To stop: scripts\stop_windows.bat
echo ========================================
echo.
pause
