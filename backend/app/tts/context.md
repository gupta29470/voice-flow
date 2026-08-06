# VoiceFlow TTS folder — Q&A guide

This document explains `backend/app/tts/` so you can read the code, walk someone through it, and answer interview-style questions.

**Files in this folder**

| File | Role |
|------|------|
| `base.py` | `Voice`, abstract `TTSProvider`, factory `get_provider`, `tts_language` |
| `cartesia_tts.py` | Cartesia Sonic WebSocket TTS (English + Hindi) |
| `elevenlabs_tts.py` | ElevenLabs Flash WebSocket TTS |

**How this fits the call pipeline**

```
LLM generate_reply  →  yields one sentence
         ↓
pipeline._speak_text(sentence)
         ↓
tts.stream(text, voice_id, language)  →  mulaw @ 8 kHz chunks
         ↓
Twilio Media Streams  →  caller's phone
```

TTS turns **text** into **phone audio**. Same encoding Twilio already uses (`pcm_mulaw` / `ulaw_8000` at 8 kHz) — no resample step in our code.

---

## Q1. What does the TTS folder do?

**A.** Text-to-speech for live outbound calls.

- **In:** a short string (usually one sentence from the LLM) + `voice_id` + language  
- **Out:** an async stream of **raw mulaw 8 kHz** audio bytes  

Two providers are supported: **Cartesia** (default-friendly, low latency, explicit `en`/`hi`) and **ElevenLabs** (Flash model, language inferred from text).

---

## Q2. What is `Voice`?

**A.** A dashboard-friendly description of one selectable voice.

```python
@dataclass
class Voice:
    provider: str       # "cartesia" or "elevenlabs"
    id: str             # provider's voice UUID / id
    name: str
    description: str = ""
    language: str = "en"  # "en" or "hi"
```

Used by `GET /api/voices` so the New Call form can filter English vs Hindi voices.

---

## Q3. What is `TTSProvider`?

**A.** The abstract contract every TTS backend implements.

```python
class TTSProvider:
    name: str = "base"

    async def stream(self, text: str, voice_id: str, language: str = "en"):
        """Yield mulaw @ 8kHz chunks for `text`."""
        ...

    async def list_voices(self) -> list[Voice]:
        ...
```

| Method | Job |
|--------|-----|
| `stream` | Synthesize one utterance; yield audio as soon as chunks arrive |
| `list_voices` | Fetch voices for the UI picker |

**Why stream (not one big blob)?** Time-to-first-audio (TTFB). The caller hears sound after the first chunk, while later chunks are still generating — same latency idea as sentence-streaming the LLM.

---

## Q4. What does `get_provider` do?

**A.** Factory that returns a live provider instance by name.

```python
get_provider("cartesia")    # → CartesiaTTS()
get_provider("elevenlabs")  # → ElevenLabsTTS()
```

Imports are **inside** the function so a missing Cartesia dependency cannot break ElevenLabs (and vice versa). Unknown names raise `ValueError`.

The pipeline picks one at call start:

```python
self.tts = get_provider(session.tts_provider)
```

---

## Q5. What does `tts_language` do?

**A.** Maps the **call language** (app concept) to a **TTS language code**.

```python
def tts_language(call_language: str) -> str:
    return "en" if call_language == "en" else "hi"
```

| Call language | TTS `language` arg |
|---------------|--------------------|
| `en` | `en` |
| `hi` | `hi` |
| `hinglish` | `hi` |

Hinglish has no separate Cartesia code — Hindi TTS + Hinglish LLM text is the practical combo. Pipeline always passes this into `stream(...)`.

---

## Q6. How does Cartesia `stream` work?

**A.** Open a WebSocket, send one complete synthesis request, yield audio chunks until `done`.

```
wss://api.cartesia.ai/tts/websocket?api_key=...&cartesia_version=2025-04-16
```

Request payload (simplified):

```json
{
  "model_id": "sonic-3.5",
  "transcript": "Thanks, Rahul.",
  "voice": { "mode": "id", "id": "<voice_id>" },
  "language": "en",
  "output_format": {
    "container": "raw",
    "encoding": "pcm_mulaw",
    "sample_rate": 8000
  },
  "context_id": "<uuid>",
  "continue": false
}
```

| Field | Why |
|-------|-----|
| `pcm_mulaw` + `8000` | Exact Twilio Media Streams format |
| `language` | Important for Hindi pronunciation |
| `continue: false` | This request is a full utterance (one sentence) |
| `context_id` | Unique id per request |

Incoming messages:

| `type` | Action |
|--------|--------|
| `chunk` + `data` | `yield base64.b64decode(data)` |
| `done` | stop |
| `error` | raise |

---

## Q7. How does ElevenLabs `stream` work?

**A.** Multi-message WebSocket protocol on the stream-input endpoint.

```
wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input
  ?model_id=eleven_flash_v2_5
  &output_format=ulaw_8000
```

Three sends in order:

1. **Handshake** — space `" "`, API key, voice settings  
2. **Text** — the sentence + `try_trigger_generation: true` (start synth immediately, don’t over-buffer)  
3. **Flush** — `{"text": ""}` means end of input  

Then yield every message with `audio` (base64 → bytes) until `isFinal`.

**Language note:** Flash infers language from the text. The `language` argument is accepted for a uniform `TTSProvider.stream` signature, then discarded (`del language`).

---

## Q8. Cartesia vs ElevenLabs — when to pick which?

| | Cartesia | ElevenLabs |
|--|----------|------------|
| Model (config) | `sonic-3.5` | `eleven_flash_v2_5` |
| Output | `pcm_mulaw` 8 kHz | `ulaw_8000` |
| Language control | Explicit `language` field | Inferred from text |
| Hindi voices | Listed from API (`en` + `hi`) | Labels often English-tagged; UI may show provider list as fallback |
| Typical pitch | Ultra-low latency | Strong voice quality |

Both are **pluggable** behind the same interface — the dashboard lets the user choose per call.

---

## Q9. How does `list_voices` work?

### Cartesia

- HTTP GET `/voices?language=en|hi&limit=8` for each language  
- Builds `Voice(..., language=en|hi)` for the picker  

### ElevenLabs

- HTTP GET `/v1/voices`, take first 12  
- Read `labels.language` when present; default `"en"`  
- Normalize `hi*` → `hi`, `en*` → `en`  

Frontend filters by call language (`voiceLanguageForCall`) so Hindi calls prefer Hindi-tagged voices.

---

## Q10. How does the pipeline call TTS?

**A.** One sentence → one `stream` → many Twilio frames.

```python
async def _speak_text(self, text, timer=None) -> int:
    lang = tts_language(self.session.language)
    sent = 0
    async for chunk in self.tts.stream(text, self.session.voice_id, language=lang):
        if timer and timer.metrics.tts_ms is None:
            timer.tts_first_audio()   # latency: tts_start → first chunk
        await self._send_audio(chunk)
        sent += len(chunk)
    return sent
```

And the agent turn looks like:

```python
async for sentence in generate_reply(self.session):
    await self._speak_text(sentence, turn_timer)
```

So latency stacks as:

```
STT final → LLM first sentence → TTS first audio chunk → caller hears
```

---

## Q11. What happens on barge-in while TTS is playing?

**A.** The pipeline cancels `_speak_task` and calls Twilio `clear`.

- Cancelling the task stops consuming further TTS chunks (and cancels `generate_reply` if still streaming sentences).  
- `clear_audio` drops audio already buffered in Twilio so the caller doesn’t keep hearing the bot over themselves.  

TTS providers don’t need a special “cancel API” — abandoning the WebSocket / generator is enough for this demo.

---

## Q12. Why mulaw 8 kHz end-to-end?

**A.** Twilio phone audio is traditionally 8 kHz μ-law.

If TTS returned 24 kHz PCM, you’d need convert → mulaw → send, adding CPU and latency. Requesting Twilio’s format from the provider keeps the path:

```
provider chunk  →  base64 JSON media event  →  Twilio  →  PSTN
```

Same idea as STT accepting mulaw 8 kHz **in**.

---

## Q13. Walk through one spoken sentence

1. LLM yields `"Thanks, Rahul."`  
2. `_speak_text` maps language (`en` / `hi`) and calls `tts.stream(...)`.  
3. Provider opens WebSocket, starts synthesis.  
4. First audio chunk arrives → metrics mark TTS (+ maybe e2e) → `_send_audio` to Twilio.  
5. More chunks stream until provider says done / `isFinal`.  
6. Next LLM sentence (if any) repeats the same path.  
7. If caller interrupts mid-stream → cancel + clear.

---

## Q14. What should you say in an interview about this folder?

**Short version**

> TTS is a pluggable interface with Cartesia and ElevenLabs behind `TTSProvider`. Each `stream` call synthesizes one sentence as mulaw 8 kHz so it goes straight to Twilio. Combined with LLM sentence streaming, we optimize time-to-first-audio. Call language maps to `en`/`hi` for Cartesia; ElevenLabs Flash infers language from text. Voices are listed over HTTP for the dashboard picker.

**Deeper if asked about latency**

> We don’t wait for the full LLM reply or the full TTS buffer. First sentence → first TTS chunk is what the caller perceives. Metrics capture TTS TTFB separately from STT and LLM.

**Deeper if asked about Hindi**

> Cartesia gets an explicit `language` and we list Hindi voices. Hinglish calls use `hi` for TTS. ElevenLabs relies on the model reading the script.

---

## Quick reference — mental model

```
base.py           →  Voice + TTSProvider + get_provider + tts_language
cartesia_tts.py   →  Sonic WS, explicit language, mulaw 8k
elevenlabs_tts.py →  Flash stream-input WS, ulaw_8000
```

```
stream(text)  =  text → mulaw chunks (async generator)
list_voices() =  provider catalog for UI
pipeline      =  one LLM sentence → one stream → Twilio
```

```
Phone audio → STT → text → LLM → sentences → TTS → Phone audio
```
