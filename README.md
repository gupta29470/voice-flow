# VoiceFlow

Real-time voice AI platform that makes **actual phone calls**. Pick a call
workflow (loan recovery, EMI reminder, banking info, sales), fill in the
details, choose a voice and language, and an AI agent dials a real phone
number and holds a natural conversation — with interruptions, memory,
tool calling, and per-stage latency instrumentation.

Built from scratch on a cascaded streaming pipeline — no realtime API, no
orchestration framework — to keep every stage observable and swappable.

## Demo

<!-- Add a link to your demo video or live deployment here -->

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

## Features

- **Real PSTN calls** via Twilio Media Streams (8kHz mulaw end-to-end, zero audio conversion)
- **Cascaded pipeline**: Deepgram streaming STT → LLM (function calling) → Cartesia / ElevenLabs streaming TTS
- **Barge-in & turn-taking**: STT endpointing + cancellable speak tasks + Twilio `clear` events — interrupt the agent mid-sentence
- **Sentence-level streaming** from LLM to TTS for low time-to-first-audio
- **Tool calling**: `log_promise_to_pay`, `lookup_loan_details`, `escalate_to_human`, `end_call` — outcomes land on the dashboard
- **Multilingual**: English / Hindi / Hinglish per call
- **Live human handoff**: escalations redirect the call leg to a human number (cold transfer)
- **Pluggable TTS**: Cartesia and ElevenLabs behind one provider interface, A/B selectable per call
- **Latency observability**: per-turn STT / LLM / TTS / end-to-end timings with avg + p95 on the call detail page
- **Workflows as config**: a new call category is one dict — system prompt, form fields, opening line, tool whitelist
