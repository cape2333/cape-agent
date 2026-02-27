#!/bin/bash
# Start both frontend and backend for development

# Start backend
echo "Starting backend..."
cd "$(dirname "$0")/../backend"
python3 main.py &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..30}; do
  if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    echo "Backend ready!"
    break
  fi
  sleep 1
done

# Start frontend
echo "Starting frontend..."
cd "$(dirname "$0")/../frontend"
npm run start &
FRONTEND_PID=$!

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

wait
