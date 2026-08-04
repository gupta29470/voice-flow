# VoiceFlow

Real-time voice AI platform that makes **actual phone calls**. Pick a call
workflow (loan recovery, EMI reminder, banking info, sales), fill in the
details, choose a voice and language, and an AI agent dials a real phone
number and holds a natural conversation — with interruptions, memory,
tool calling, and per-stage latency instrumentation.

Built from scratch on a cascaded streaming pipeline — no realtime API, no
orchestration framework — to keep every stage observable and swappable.

## Features

- **Real PSTN calls** via Twilio Media Streams (8kHz mulaw end-to-end, zero audio conversion)
- **Cascaded pipeline**: Deepgram streaming STT → LLM (function calling) → Cartesia / ElevenLabs streaming TTS
- **Barge-in & turn-taking**: STT endpointing + cancellable speak tasks + Twilio `clear` events — interrupt the agent mid-sentence
- **Sentence-level streaming** from LLM to TTS for low time-to-first-audio
- **Tool calling**: `log_promise_to_pay`, `lookup_loan_details`, `escalate_to_human`, `end_call` and more — outcomes land on the dashboard
- **Multilingual**: English / Hindi / Hinglish per call
- **Live human handoff**: escalations redirect the call leg to a human number (cold transfer)
- **Pluggable TTS**: Cartesia and ElevenLabs behind one provider interface, A/B selectable per call
- **Latency observability**: per-turn STT / LLM / TTS / end-to-end timings with avg + p95 on the call detail page
- **Workflows as config**: a new call category is one dict — system prompt, form fields, opening line, tool whitelist

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

## Stack

| Layer | Tech |
|---|---|
| Telephony | Twilio Media Streams |
| STT | Deepgram streaming (`nova-2-phonecall`) |
| LLM | Kimi K2.7 via OpenAI-compatible API (streaming + function calling) |
| TTS | Cartesia Sonic 3.5 + ElevenLabs Flash v2.5 (pluggable interface) |
| Backend | Python, FastAPI, WebSockets, SQLite |
| Frontend | Next.js, TypeScript, Tailwind |
| Deploy | Railway (backend), Vercel (frontend) |

## Project structure

```
backend/
  app/
    main.py             # FastAPI app + REST API for the dashboard
    config.py           # env-based settings (pydantic)
    media_stream.py     # Twilio Media Streams WebSocket gateway
    pipeline.py         # per-call orchestrator: STT → LLM → TTS, barge-in
    twilio_handler.py   # outbound calls, hangup, transfer, TwiML webhook
    session.py          # call state: memory, transcript, outcome
    metrics.py          # per-turn latency instrumentation
    storage.py          # SQLite: calls, transcripts, metrics
    audio.py            # base64 helpers
    stt/                # STT interface + Deepgram streaming client
    llm/                # workflows (config), tools, streaming agent
    tts/                # TTS interface + Cartesia + ElevenLabs
frontend/
  app/                  # dashboard + call detail pages
  components/           # call form, recent calls, status, skeletons
  lib/                  # typed API client
```

## Run locally

Prereqs: Python 3.11+, Node 18+, and API keys — Twilio (trial works),
Deepgram, Kimi, Cartesia and/or ElevenLabs.

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in your keys
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                 # http://localhost:3000

# For real phone calls (third terminal) — Twilio must reach your machine
ngrok http 8000
# → put the https URL into backend/.env as PUBLIC_URL, restart the backend
```

Or run both with `./dev.sh`.

> Twilio trial notes: calls only work to **verified numbers** (console →
> Verified Caller IDs), and calls play a short trial message first. Both
> limits disappear on a paid account.

## Deploy

- **Backend → Railway**: root directory `backend`, start command
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, set all env vars
  with `PUBLIC_URL` = the Railway domain and `FRONTEND_URL` = the Vercel domain.
- **Frontend → Vercel**: root directory `frontend`, env
  `NEXT_PUBLIC_API_URL` = the Railway domain.
- No Twilio console change needed — the webhook URL is built per call
  from `PUBLIC_URL`.

## Roadmap

- Warm transfer via Twilio Conferencing (human joins before the AI drops)
- Silero VAD alongside Deepgram endpointing
- Benchmark harness: scripted calls, TTS time-to-first-audio comparison
- More Indian languages (Tamil, Telugu, Marathi — supported by Sonic 3.5)
- WhatsApp follow-up flows
