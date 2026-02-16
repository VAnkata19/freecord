@echo off
REM ── Freecord: Windows Stop Script ──

echo Stopping Freecord services...

REM Kill by window title
taskkill /FI "WINDOWTITLE eq Freecord-Rust*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Freecord-FastAPI*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Freecord-Flask*" /F >nul 2>&1

REM Fallback: kill by port
for %%p in (8001 8000 5000) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
        taskkill /PID %%a /F >nul 2>&1
        echo   Killed process on port %%p (PID %%a)
    )
)

echo All services stopped.
pause
