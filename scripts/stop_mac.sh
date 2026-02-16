#!/bin/bash
# ── Freecord: macOS Stop Script ──

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.pids"

echo "Stopping Freecord services..."

if [ -f "$PID_FILE" ]; then
    while read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "  Stopped PID $pid"
        fi
    done < "$PID_FILE"
    rm "$PID_FILE"
else
    echo "  No PID file found. Killing by port..."
fi

# Fallback: kill processes on known ports
for port in 8001 8000 5000; do
    pid=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$pid" ]; then
        kill $pid 2>/dev/null
        echo "  Killed process on port $port (PID $pid)"
    fi
done

echo "All services stopped."
