#!/bin/bash
# Start both frontend and backend for development

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PORT_FILE="$PROJECT_DIR/.backend_port"

# Clean up stale port file
rm -f "$PORT_FILE"

# Start backend in background
echo "Starting backend..."
cd "$PROJECT_DIR/backend"
CAPE_AGENT_RELOAD=1 python3 main.py &
BACKEND_PID=$!

# Cleanup on exit
trap "kill $BACKEND_PID 2>/dev/null; rm -f $PORT_FILE" EXIT

# Wait for port file to be written
echo "Waiting for backend port..."
for i in {1..10}; do
  if [ -f "$PORT_FILE" ]; then
    break
  fi
  sleep 0.5
done

if [ ! -f "$PORT_FILE" ]; then
  echo "ERROR: Backend failed to write port file"
  exit 1
fi

BACKEND_PORT=$(cat "$PORT_FILE")
echo "Backend port: $BACKEND_PORT"

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..30}; do
  if curl -s "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then
    echo "Backend ready!"
    break
  fi
  sleep 1
done

# Start frontend in foreground (GUI app needs foreground on macOS)
echo "Starting frontend..."
cd "$PROJECT_DIR/frontend"
npm run start
