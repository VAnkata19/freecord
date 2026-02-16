#!/bin/bash
# ── Freecord: Linux Run Script ──
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "  Freecord - Starting all services"
echo "========================================"
echo ""

# ── Check prerequisites ──

echo "[1/7] Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo "Install it via: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
echo "  Python3: $(python3 --version)"

if ! command -v cargo &> /dev/null; then
    echo "ERROR: Rust/Cargo is not installed."
    echo "Install it via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi
echo "  Cargo: $(cargo --version)"

# ── Set environment variables ──

echo "[2/7] Setting environment variables..."

export MASTER_SECRET="${MASTER_SECRET:-my-super-secret-master-key-change-me}"
export RUST_LOG="${RUST_LOG:-info}"
export JWT_SECRET="${JWT_SECRET:-change-this-jwt-secret-key}"
export RUST_SERVICE_URL="${RUST_SERVICE_URL:-http://127.0.0.1:8001}"
export FLASK_SECRET="${FLASK_SECRET:-change-this-flask-secret}"
export API_URL="${API_URL:-http://127.0.0.1:8000}"

if [ -f "$PROJECT_DIR/.env" ]; then
    echo "  Loading .env file..."
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# ── Build and start Rust encryption service ──

echo "[3/7] Building Rust encryption service..."
cd "$PROJECT_DIR/rust_encryption_service"
cargo build --release 2>&1 | tail -5

echo "[4/7] Starting Rust encryption service on port 8001..."
cargo run --release &
RUST_PID=$!
echo "  PID: $RUST_PID"

echo "  Waiting for Rust service..."
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8001/health > /dev/null 2>&1; then
        echo "  Rust service is ready!"
        break
    fi
    sleep 1
done

# ── Set up FastAPI backend ──

echo "[5/7] Setting up FastAPI backend..."
cd "$PROJECT_DIR/backend_fastapi"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo "  Starting FastAPI backend on port 8000..."
python -m uvicorn main:app --host 127.0.0.1 --port 8000 &
FASTAPI_PID=$!
echo "  PID: $FASTAPI_PID"
deactivate

echo "  Waiting for FastAPI..."
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:8000/ > /dev/null 2>&1; then
        echo "  FastAPI is ready!"
        break
    fi
    sleep 1
done

# ── Set up Flask frontend ──

echo "[6/7] Setting up Flask frontend..."
cd "$PROJECT_DIR/frontend_flask"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo "  Starting Flask frontend on port 5000..."
python app.py &
FLASK_PID=$!
echo "  PID: $FLASK_PID"
deactivate

sleep 2

# ── Save PIDs ──

echo "$RUST_PID" > "$PROJECT_DIR/scripts/.pids"
echo "$FASTAPI_PID" >> "$PROJECT_DIR/scripts/.pids"
echo "$FLASK_PID" >> "$PROJECT_DIR/scripts/.pids"

# ── Open browser ──

echo "[7/7] Opening browser..."
if command -v xdg-open &> /dev/null; then
    xdg-open http://127.0.0.1:5000
elif command -v sensible-browser &> /dev/null; then
    sensible-browser http://127.0.0.1:5000
fi

echo ""
echo "========================================"
echo "  All services are running!"
echo ""
echo "  Frontend:    http://127.0.0.1:5000"
echo "  Backend API: http://127.0.0.1:8000"
echo "  Encryption:  http://127.0.0.1:8001"
echo ""
echo "  To stop: ./scripts/stop_linux.sh"
echo "========================================"
echo ""

wait
