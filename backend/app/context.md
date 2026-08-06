# VoiceFlow `app/` core — Q&A guide

One-file guide to the **top-level** modules under `backend/app/` (everything beside the `llm/`, `stt/`, `tts/` packages).

For deeper STT / LLM / TTS detail, see:

- [`stt/context.md`](stt/context.md)
- [`llm/context.md`](llm/context.md)
- [`tts/context.md`](tts/context.md)

**Files covered here**

| File | One-line role |
|------|----------------|
| `main.py` | FastAPI app + REST API for the dashboard |
| `config.py` | Env settings (keys, models, URLs, demo flag) |
| `storage.py` | SQLite: calls, transcripts, turn metrics |
| `session.py` | In-memory state for one live call |
| `twilio_handler.py` | Place / hangup / transfer + TwiML voice webhook |
| `media_stream.py` | Twilio Media Streams WebSocket gateway |
| `pipeline.py` | Orchestrates STT → LLM → TTS for one call |
| `metrics.py` | Per-turn latency timer (STT / LLM / TTS / e2e) |
| `audio.py` | Base64 ↔ mulaw bytes for Twilio JSON frames |

---

## Big picture — how a call flows through these files

```
Dashboard (Next.js)
    │  POST /api/calls
    ▼
main.py ──► storage.create_call
         ──► twilio_handler.place_call
                │
                ▼  callee answers
         twilio_handler.voice_webhook  (TwiML → <Stream>)
                │
                ▼  WebSocket
         media_stream.py
                │ builds CallSession + injects send/clear/hangup/transfer
                ▼
         pipeline.py  (CallPipeline)
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
   STT        LLM        TTS     (+ metrics.TurnTimer)
     │          │          │
     └──────────┴──────────┘
                │
         media_stream send_audio / clear
                │
              Twilio → phone
```

---

## Q1. What is `main.py`?

**A.** The FastAPI entrypoint: wires middleware, routers, and the dashboard REST API.

### Startup

```python
@asynccontextmanager
async def lifespan(app):
    storage.init_db()   # create SQLite tables
    yield
```

### Included routers

| Router | Path | Source |
|--------|------|--------|
| Twilio voice | `POST /twilio/voice` | `twilio_handler` |
| Media stream | `WS /twilio/stream` | `media_stream` |

### REST endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness |
| `GET` | `/api/config` | `{ app_active }` for demo mode UI |
| `GET` | `/api/workflows` | Form schema for New Call |
| `GET` | `/api/voices` | Cartesia + ElevenLabs voices (5 min cache) |
| `POST` | `/api/calls` | Create call + ask Twilio to dial |
| `GET` | `/api/calls` | Recent calls list |
| `GET` | `/api/calls/{id}` | Detail: transcript, metrics, capture |

### `POST /api/calls` steps

1. Reject if `app_active` is false (demo lock)  
2. Validate workflow / TTS provider / language  
3. `storage.create_call(...)` including `llm_provider` / `llm_model`  
4. `place_call(call_id, phone)` → store Twilio SID  
5. Return `{ call_id, status: "initiated" }`  

CORS is open (`*`) for a demo with no auth — fine for portfolio, tighten if you add login.

---

## Q2. What is `config.py`?

**A.** Central settings loaded from `.env` via Pydantic `BaseSettings`.

Groups of settings:

| Group | Examples |
|-------|----------|
| Twilio | `twilio_account_sid`, `twilio_auth_token`, `twilio_phone_number` |
| Vendor keys | Deepgram, Grok, Kimi, Cartesia, ElevenLabs |
| URLs | `public_url` (Twilio webhooks), `frontend_url` |
| Models | `deepgram_model`, `cartesia_model`, `grok_model`, … |
| Ops | `database_path`, `human_handoff_number`, `app_active` |

### LLM provider selection

```python
llm_provider  →  "grok" if GROK_API_KEY set else "kimi"
llm_api_key / llm_base_url / llm_model  →  matching pair
```

Single `settings = Settings()` singleton imported everywhere.

**Interview angle:** config is the only place secrets/models live; app code reads properties, not hard-coded keys.

---

## Q3. What is `storage.py`?

**A.** Thin SQLite persistence layer (no ORM).

### Tables

| Table | Stores |
|-------|--------|
| `calls` | Workflow, phone, voice, language, status, outcome, capture JSON, Twilio SID, times |
| `transcripts` | Per-line agent/caller text with timestamp |
| `turn_metrics` | Per-turn `stt_ms`, `llm_ms`, `tts_ms`, `e2e_ms` |

### Important functions

| Function | Role |
|----------|------|
| `init_db` | Create tables + migrate missing columns (`llm_*`, `capture_json`) |
| `create_call` | Insert row, return short hex `call_id` |
| `update_call` | Patch arbitrary columns |
| `end_call_record` | Set status, `ended_at`, compute `duration_sec` |
| `add_transcript` / `add_turn_metrics` | Append rows during the call |
| `list_calls` | Last 50 for Recent Calls |
| `get_call` | Full detail + transcript + avg/p95 metrics |

**Why SQLite?** Demo-scale, zero ops, file on disk (`voiceflow.db`). Enough for portfolio; swap later if needed.

---

## Q4. What is `session.py` (`CallSession`)?

**A.** **In-memory** state for one live call — the object the pipeline and tools mutate.

Created in `media_stream` when Twilio’s stream `start` event arrives.

### What it holds

| Field | Meaning |
|-------|---------|
| `messages` | LLM chat history (starts with rendered system prompt + language rules) |
| `context` | Form fields (borrower name, amount, …) |
| `workflow` | Which workflow config |
| `tts_provider` / `voice_id` / `language` | How to speak |
| `outcome` / `capture` | Structured result for the dashboard |
| `end_requested` / `transfer_requested` | Tool flags for hangup / handoff |
| `turn` | Caller turn counter (used by `end_call` safety gate) |

### Key methods

| Method | Does |
|--------|------|
| `_render` | Fill `{placeholders}` from context |
| `opening_line()` | First English greeting |
| `add_user_message` | Append user + write transcript |
| `add_assistant_message` | Append assistant + write transcript |
| `set_capture` | Save structured tool result to DB |
| `deepgram_language` | `en` or `hi` (Hinglish → `hi`) |

**Session vs storage:** session is live RAM; storage is durable history the UI polls.

---

## Q5. What is `twilio_handler.py`?

**A.** All Twilio **REST + TwiML** for the call lifecycle (not the media WebSocket).

| Function | Role |
|----------|------|
| `place_call(call_id, to)` | Outbound dial; webhook URL includes `call_id` |
| `voice_webhook` | Returns TwiML `<Connect><Stream>` pointing at `/twilio/stream` |
| `hangup_call(sid)` | Set call status `completed` |
| `transfer_call(sid)` | Cold transfer: update live call TwiML to `<Dial>` handoff number |

### TwiML idea

When the callee answers, Twilio fetches:

```
POST /twilio/voice?call_id=abc123
```

Response tells Twilio: open a bidirectional audio WebSocket to us, and pass `call_id` as a stream parameter so we can load the right DB row / workflow.

`public_url` must be publicly reachable (ngrok / Render) — Twilio cannot hit `localhost`.

---

## Q6. What is `media_stream.py`?

**A.** The **gateway** between Twilio Media Streams JSON and `CallPipeline`.

WebSocket: `/twilio/stream`

### Events

| Twilio event | What we do |
|--------------|------------|
| `start` | Load call from DB → build `CallSession` → inject audio callbacks → `pipeline.start()` |
| `media` | Decode base64 payload → `pipeline.handle_audio(bytes)` |
| `stop` / disconnect | `pipeline.shutdown()` |

### Injected callbacks (dependency injection)

The pipeline never imports Twilio. The gateway gives it:

```python
send_audio(chunk)  →  WS {"event":"media", "media":{"payload": b64}}
clear_audio()      →  WS {"event":"clear"}   # barge-in
hangup()           →  hangup_call(call_sid)
transfer()         →  transfer_call(call_sid)
```

**Interview angle:** clean boundary — telephony protocol at the edge, conversation logic in the pipeline.

---

## Q7. `/twilio/voice` vs `/twilio/stream` — what connects where?

**A.** Two different Twilio → backend connections. Only one carries audio.

Both use `settings.public_url` (must be publicly reachable — ngrok / Render — not bare `localhost`).

| Endpoint | Transport | Who dials whom | Carries audio? |
|----------|-----------|----------------|----------------|
| `POST /twilio/voice` | HTTP webhook | **Twilio calls us** when callee answers | **No** — only returns TwiML instructions |
| `WS /twilio/stream` | WebSocket | **Twilio opens WS to us** after reading TwiML | **Yes — both directions** |

Wired in `main.py`:

```python
app.include_router(twilio_router)   # /twilio/voice
app.include_router(media_router)    # /twilio/stream
```

### Where each URL is set

**1. Voice webhook** — when we place the call (`twilio_handler.place_call`):

```python
url=f"{settings.public_url}/twilio/voice?call_id={call_id}"
```

**2. Media stream** — TwiML returned by `voice_webhook`:

```xml
<Connect>
  <Stream url="wss://{PUBLIC_URL}/twilio/stream">
    <Parameter name="call_id" value="{call_id}" />
  </Stream>
</Connect>
```

The WS handler that accepts it is `twilio_stream` in `media_stream.py`:

```python
@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket) -> None:
    await ws.accept()
```

### Common misconception

| Wrong mental model | Correct |
|--------------------|---------|
| `/twilio/voice` = caller audio in | `/twilio/voice` = setup only (TwiML). **No audio.** |
| `/twilio/stream` = agent audio out only | `/twilio/stream` = **caller in + agent out** on one socket |
| Frontend connects to Twilio stream | **Twilio** connects to **our** backend. Frontend never joins that WS |

### When the user picks up — is the WebSocket bidirectional?

**Yes.** Sequence:

1. Callee answers  
2. Twilio **POST** `/twilio/voice?call_id=...` → we return TwiML `<Stream>`  
3. Twilio opens **one** WebSocket to `/twilio/stream`  
4. That same socket carries:
   - **In:** caller speech → us → Deepgram  
   - **Out:** TTS audio → Twilio → caller hears it  
   - Also `clear` for barge-in  
5. Stays open until stream `stop` / disconnect  

```
Answer
  └─ Twilio POST /twilio/voice  →  TwiML “please stream”
         └─ Twilio WS /twilio/stream  ↔  audio both ways
```

### Dashboard vs phone audio (two planes)

| Plane | Path |
|-------|------|
| **Audio (phone)** | Phone ↔ Twilio ↔ `/twilio/stream` ↔ pipeline (STT/LLM/TTS) |
| **Dashboard (UI)** | Browser ↔ REST `GET /api/calls/{id}` (poll transcript/status). **No media WS.** |

Twilio is input **and** output for the live call. The dashboard only renders chat bubbles from SQLite transcript rows written during the call — it does not play Cartesia/Twilio audio.

---

## Q8. What is `pipeline.py` (`CallPipeline`)?

**A.** The **orchestrator for one phone call**: STT loop, barge-in, LLM replies, TTS play-out, hangup/transfer.

One instance = one call.

### Lifecycle

1. `start()` → background `run()` task  
2. Connect Deepgram; flush any prebuffered Twilio audio  
3. Agent speaks first (English opening line, or LLM open for hi/hinglish)  
4. Forever: `async for event in stt.events()` → `_on_stt_event`  
5. On shutdown/error: cancel speak, close STT, `end_call_record`

### Turn handling (`_on_stt_event`)

| Event | Behavior |
|-------|----------|
| `interim` | Barge-in: cancel speak + `clear_audio` |
| `final` (not speech_final) | Append to `_utterance_parts` |
| `final` + `speech_final` | Join utterance → user message → `_respond` task |

### `_respond`

- Stream sentences from `generate_reply`  
- Each sentence → `_speak_text` → TTS → `send_audio`  
- Record latency via `TurnTimer`  
- If `end_requested` / `transfer_requested`: wait for Twilio buffer to drain, then hangup/transfer  

### `_speak_text`

- `tts.stream(text, voice_id, language)`  
- First chunk marks TTS + e2e metrics  
- Returns bytes sent (used to estimate drain time before hangup)  

### What is `_prebuffer`?

A short queue of **Twilio audio chunks that arrive before Deepgram STT is connected**.

```python
self._prebuffer: list[bytes] = []  # audio arriving before STT connects
```

On stream `start`, the pipeline does `stt.connect()` (network handshake). Twilio may already be sending `media` frames during that gap. Without a buffer, those early bytes would be **dropped**.

How it works:

1. `handle_audio(chunk)`:
   - if STT ready → `stt.send(chunk)` immediately  
   - else → append to `_prebuffer` (cap ~250 frames ≈ 5 seconds, then drop)
2. After `await self.stt.connect()`:
   - flush every buffered chunk into Deepgram  
   - clear `_prebuffer`

```
Twilio media ──► handle_audio
                    │
         STT not ready? ──yes──► _prebuffer
                    │ no
                    ▼
              stt.send(chunk)
```

### What is `_utterance_parts`?

A list that **collects final STT phrases until the caller’s full turn is done**.

```python
self._utterance_parts: list[str] = []
```

Deepgram can emit several `final` transcripts before `speech_final=True` (end of turn). Example:

1. `final` → `"I can pay"`
2. `final` → `"ten thousand"`
3. `final` + `speech_final` → `"by August tenth"`

You don’t want to call the LLM after each piece — you’d interrupt mid-thought.

How it works:

```python
self._utterance_parts.append(event.text)   # each final phrase
if not event.speech_final:
    return                                 # still talking — wait

utterance = " ".join(self._utterance_parts).strip()
self._utterance_parts = []                 # reset for next turn
# → send full utterance to LLM
```

| Buffer | Holds | Until |
|--------|-------|-------|
| `_prebuffer` | Early **audio bytes** | Deepgram connects |
| `_utterance_parts` | Final **text fragments** | `speech_final` (caller turn done) |

**This is the file to open first** when explaining “how does a live call actually work?”

---

## Q9. What is `metrics.py`?

**A.** Per-caller-turn latency instrumentation.

```python
TurnTimer(call_id, turn)
  .mark("final_transcript")
  .set_mark("audio_sent", stt.last_audio_sent_at)
  .stt_done()           # audio_sent → now
  .mark("llm_start")
  .llm_first_sentence() # llm_start → first sentence
  .mark("tts_start")
  .tts_first_audio()    # tts_start → first audio chunk
  .first_audio_out()    # final_transcript → first audio out (e2e)
  .save()               # → storage.add_turn_metrics
```

| Metric | Measures |
|--------|----------|
| `stt_ms` | Last audio to Deepgram → final turn ready |
| `llm_ms` | LLM start → first speakable sentence |
| `tts_ms` | TTS start → first audio chunk |
| `e2e_ms` | Final transcript → first audio out to Twilio |

Dashboard shows averages + e2e p95 from `storage.get_call`.

---

## Q10. What is `audio.py`?

**A.** Tiny helpers for Twilio’s JSON media framing.

```python
b64_to_bytes(payload)  # Twilio → us  (inbound media)
bytes_to_b64(data)     # us → Twilio  (outbound media)
```

Twilio sends/receives mulaw as **base64 inside JSON**, not raw binary WebSocket frames. This module is the only place that cares about that encoding detail.

---

## Q11. Who owns what? (responsibility map)

| Concern | Owner |
|---------|--------|
| HTTP API / CORS / validation | `main.py` |
| Secrets & feature flags | `config.py` |
| Durable call data | `storage.py` |
| Live conversation state | `session.py` |
| Dial / TwiML / hangup / transfer | `twilio_handler.py` |
| Twilio WS ↔ pipeline bridge | `media_stream.py` |
| Turn-taking + STT/LLM/TTS loop | `pipeline.py` |
| Latency marks | `metrics.py` |
| Base64 mulaw encode/decode | `audio.py` |
| Prompts, tools, model stream | `llm/` |
| Speech → text | `stt/` |
| Text → speech | `tts/` |

---

## Q12. Walk through one full call (all files)

1. User submits form → **`main.start_call`**  
2. **`storage.create_call`** → row `initiated`  
3. **`twilio_handler.place_call`** → phone rings  
4. Answer → Twilio hits **`voice_webhook`** → TwiML Stream  
5. **`media_stream`** `start` → **`CallSession`** + **`CallPipeline.start`**  
6. Pipeline opening line → **TTS** → **`audio.bytes_to_b64`** → Twilio  
7. Caller speaks → media frames → **`b64_to_bytes`** → **STT**  
8. `speech_final` → **`session.add_user_message`** → **`generate_reply`**  
9. Sentences → TTS → phone; tools may set capture / end / transfer  
10. **`TurnTimer.save`** → metrics row  
11. Hangup or stream stop → **`pipeline.shutdown`** → **`storage.end_call_record`**  
12. Dashboard polls **`GET /api/calls/{id}`** → transcript + metrics + capture  

---

## Q13. What should you say in an interview about this layer?

**Short version**

> The core app is a cascaded voice pipeline behind FastAPI. REST creates the call and Twilio dials; a Media Streams WebSocket gateway feeds audio into a per-call pipeline that runs Deepgram STT, an LLM with tools, and Cartesia/ElevenLabs TTS. Session holds live state, SQLite persists transcripts and latency, and Twilio hangup/transfer stay at the edge via injected callbacks so the pipeline stays telephony-agnostic.

**If asked “why not a realtime API?”**

> Every stage is observable and swappable — we measure STT/LLM/TTS separately and can change one vendor without rewriting the others.

---

## Quick reference — file cheat sheet

```
main.py            →  REST + app wiring
config.py          →  .env settings + LLM provider pick
storage.py         →  SQLite CRUD
session.py         →  live CallSession
twilio_handler.py  →  dial / TwiML / hangup / transfer
media_stream.py    →  WS gateway (Twilio ↔ pipeline)
pipeline.py        →  STT ↔ LLM ↔ TTS orchestrator
metrics.py         →  per-turn latency
audio.py           →  base64 mulaw helpers
```

```
API creates call → Twilio dials → Stream WS → Pipeline runs the conversation
```

```
/twilio/voice   = HTTP setup (TwiML only, no audio)
/twilio/stream  = one bidirectional WS (caller in + agent out)
Dashboard       = REST poll of transcript — not on the audio path
```
