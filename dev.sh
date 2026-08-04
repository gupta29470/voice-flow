#!/usr/bin/env bash
# VoiceFlow dev runner — starts backend (FastAPI :8000) and frontend (Next.js :3000).
# Usage: ./dev.sh          (Ctrl+C stops both)
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

(cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

(cd "$ROOT/frontend" && npm run dev) &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null' INT TERM EXIT

echo "Backend  → http://localhost:8000  (API + Twilio webhook)"
echo "Frontend → http://localhost:3000  (dashboard)"
echo "Note: for real phone calls you still need ngrok in a third terminal:"
echo "      ngrok http 8000   →   put the https URL in backend/.env as PUBLIC_URL"
echo
wait
