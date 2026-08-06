# VoiceFlow

Real-time voice AI platform that makes **actual phone calls**. Pick a call
workflow (loan recovery, EMI reminder, banking info, sales), fill in the
details, choose a voice and language, and an AI agent dials a real phone
number and holds a natural conversation — with barge-in, memory, tool
calling, structured captures, and per-stage latency instrumentation.

Built as a cascaded streaming pipeline — no realtime API, no orchestration
framework — so every stage stays observable and swappable.

## Demo

[Watch the demo video](https://youtu.be/WMqto41-tRw)

## Architecture

```
        Caller's phone
              │ PSTN
         ┌────▼─────┐
         │  Twilio  │  places call, bridges audio
         └────┬─────┘
              │ Media Streams WebSocket (8kHz mulaw, base64 JSON)
   ┌──────────▼───────────────────────────────────────┐
   │           FastAPI backend                        │
   │  media_stream.py (gateway)                       │
   │      │                                           │
   │      ▼                                           │
   │  pipeline.py ──► Deepgram STT (streaming)        │
   │      │                transcript                 │
   │      ▼                                           │
   │  agent.py — LLM: memory, tools, sentence stream  │
   │      │                sentences                  │
   │      ▼                                           │
   │  TTS (Cartesia / ElevenLabs) ──► audio ──► Twilio│
   │                                                  │
   │  metrics.py (latency)   storage.py (SQLite)      │
   └──────────▲───────────────────────────────────────┘
              │ REST
   ┌──────────┴──────────┐
   │  Next.js dashboard  │
   └─────────────────────┘
```

Each live call gets its own WebSocket → `CallSession` → `CallPipeline`, so
several calls can run concurrently on one async FastAPI process (demo-scale).

## Stack

| Layer | Tech |
|---|---|
| Telephony | Twilio Media Streams |
| STT | Deepgram streaming (`nova-2-phonecall` for English; `nova-2` for Hindi/Hinglish) |
| LLM | **Grok** (xAI, default) via OpenAI-compatible API; **Kimi** fallback if `GROK_API_KEY` is unset |
| TTS | Cartesia Sonic 3.5 + ElevenLabs Flash v2.5 (pluggable; English + Hindi Cartesia voices) |
| Backend | Python, FastAPI, WebSockets, SQLite |
| Frontend | Next.js, TypeScript, Tailwind |
| Deploy | Backend on Render/Railway + public URL for Twilio; frontend on Vercel |

## Features

- **Real PSTN calls** via Twilio Media Streams (8kHz mulaw end-to-end)
- **Cascaded pipeline**: Deepgram STT → LLM (tools + streaming) → Cartesia / ElevenLabs TTS
- **Barge-in & turn-taking**: STT endpointing + cancellable speak tasks + Twilio `clear`
- **Sentence-level streaming** from LLM → TTS for low time-to-first-audio
- **Tool calling**: `log_promise_to_pay`, `qualify_lead`, `lookup_*`, `escalate_to_human`, `end_call`
- **Captured results**: structured promise-to-pay / lead qualify / escalate data on the call detail page
- **Multilingual**: English / Hindi / Hinglish per call (STT model + TTS `language` + voice picker)
- **Live human handoff**: cold transfer to `HUMAN_HANDOFF_NUMBER`
- **Latency observability**: per-turn STT / LLM / TTS / e2e with avg + p95; LLM provider/model shown
- **Workflows as config**: prompt, form fields, opening line, and tool whitelist in one dict
- **Demo switch**: `APP_ACTIVE=False` disables outbound calling

## Workflows

| ID | Agent | Goal |
|---|---|---|
| `loan_recovery` | Priya | Confirm identity → discuss overdue → log promise to pay |
| `emi_reminder` | Priya | Remind upcoming EMI → confirm pay-on-time |
| `banking_info` | Maya | Answer balance / branch via tools |
| `sales` | Arjun | Qualify interest → `qualify_lead` |

## Local setup

### 1. Backend

```bash
cd backend
python -m venv ../.venv 
source ../.venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in keys
```

Required in `backend/.env`:

- Twilio: `TWILIO_*`
- `DEEPGRAM_API_KEY`
- `GROK_API_KEY` (preferred) and/or `KIMI_API_KEY`
- `CARTESIA_API_KEY` and/or `ELEVENLABS_API_KEY`
- `PUBLIC_URL` — public HTTPS URL of this backend (ngrok locally)
- Optional: `HUMAN_HANDOFF_NUMBER`, `APP_ACTIVE`, `FRONTEND_URL`

### 2. Frontend

```bash
cd frontend
npm install
# optional: NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

### 3. Run

From repo root:

```bash
./dev.sh
```

- API: http://localhost:8000  
- Dashboard: http://localhost:3000  

For real calls, expose the backend and set `PUBLIC_URL`:

Twilio must be able to reach `PUBLIC_URL/twilio/voice` and
`PUBLIC_URL/twilio/stream` (WSS).

## API (high level)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/workflows` | Form schemas for the dashboard |
| `GET` | `/api/voices` | Cartesia / ElevenLabs voices (tagged `en` / `hi`) |
| `POST` | `/api/calls` | Place an outbound call |
| `GET` | `/api/calls` | Recent calls |
| `GET` | `/api/calls/{id}` | Transcript, metrics, capture, context |
| `POST` | `/twilio/voice` | TwiML answer webhook |
| `WS` | `/twilio/stream` | Bidirectional media |

## Project layout

```
backend/app/
  main.py            REST API
  media_stream.py    Twilio WebSocket gateway
  pipeline.py        Per-call STT → LLM → TTS loop
  session.py         Conversation state + captures
  llm/               Agent, tools, workflows
  stt/ tts/          Provider adapters
  storage.py         SQLite
frontend/            Next.js dashboard
```