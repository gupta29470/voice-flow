# VoiceFlow STT folder — Q&A guide

This document explains `backend/app/stt/` so you can read the code, walk someone through it, and answer interview-style questions.

**Files in this folder**

| File | Role |
|------|------|
| `base.py` | Shared contract: `STTEvent` + abstract `STTProvider` |
| `deepgram_stt.py` | Deepgram WebSocket implementation of that contract |

**How this fits the call pipeline**

```
Caller's phone
      │ PSTN
   Twilio Media Streams  (mulaw @ 8 kHz, ~20 ms frames)
      │
   pipeline.handle_audio(chunk)
      │
   DeepgramSTT.send(audio)  ──WebSocket──►  Deepgram
                                               │
   DeepgramSTT.events()   ◄── JSON results ────┘
      │
   STTEvent (interim | final)
      │
   pipeline._on_stt_event
      │
   user text → LLM → TTS → phone
```

STT turns **raw phone audio bytes** into **text events**. It does not talk to the LLM or Twilio directly — the pipeline owns that.

---

## Q1. What does the STT folder do?

**A.** Speech-to-text for live phone calls.

- **In:** continuous mulaw audio chunks (same format Twilio sends)  
- **Out:** a stream of `STTEvent`s — partial guesses (`interim`) and committed phrases (`final`), plus a “caller finished their turn” flag (`speech_final`)

Deepgram is the only provider today, but the interface is swappable (`STTProvider`).

---

## Q2. What is `STTEvent`?

**A.** One transcription update from the provider.

```python
@dataclass
class STTEvent:
    type: str              # "interim" or "final"
    text: str
    speech_final: bool = False  # endpointing: caller's turn is over
```

| Field | Meaning |
|-------|---------|
| `type="interim"` | Live partial hypothesis — text may still change |
| `type="final"` | Deepgram committed this phrase (won’t revise it) |
| `text` | The transcript string |
| `speech_final` | Only meaningful on finals: silence / endpointing says the speaker paused long enough that the **turn** is done |

### Example over one caller utterance

Caller says: *“Yes, this is Rahul.”*

| Time | Event | Notes |
|------|--------|--------|
| t1 | `interim` `"Yes"` | Barge-in can fire here |
| t2 | `interim` `"Yes this is"` | Still talking |
| t3 | `final` `"Yes this is Rahul"` `speech_final=False` | Phrase locked; maybe more coming |
| t4 | `final` `""` skipped / or next phrase | — |
| t5 | `final` `"Yes this is Rahul."` `speech_final=True` | Turn complete → send to LLM |

(Exact chunking varies; the idea is: interims → finals → `speech_final` ends the turn.)

---

## Q3. What is `STTProvider`?

**A.** The abstract interface every STT backend must implement.

```python
class STTProvider:
    async def connect(self) -> None: ...
    async def send(self, audio: bytes) -> None: ...   # mulaw @ 8 kHz
    def events(self): ...                             # async gen of STTEvent
    async def close(self) -> None: ...
```

| Method | Job |
|--------|-----|
| `connect` | Open the provider connection (Deepgram WebSocket) |
| `send` | Push one audio frame upstream |
| `events` | Yield transcription events for the life of the call |
| `close` | Clean shutdown |

**Why abstract?** So `pipeline.py` depends on “an STT,” not “Deepgram.” You could add AssemblyAI / Google later without rewriting turn-taking.

---

## Q4. How does `DeepgramSTT` connect?

**A.** It opens a Deepgram Listen WebSocket with phone-friendly query params.

```
wss://api.deepgram.com/v1/listen
  ?encoding=mulaw
  &sample_rate=8000
  &channels=1
  &model={model}
  &interim_results=true
  &endpointing=300
  &smart_format=true
  &language={language}
```

| Param | Why it matters |
|-------|----------------|
| `encoding=mulaw` + `sample_rate=8000` | Matches Twilio Media Streams — **no resample** in our code |
| `interim_results=true` | Enables barge-in (hear speech before the turn ends) |
| `endpointing=300` | ~300 ms of silence → prefer `speech_final` (turn boundary) |
| `smart_format=true` | Numbers/dates formatted more naturally |
| `language` | `en` or `hi` (Hinglish uses `hi` via session) |
| `model` | Usually `nova-2-phonecall`; falls back for non-English |

Auth header:

```python
"Authorization": f"Token {settings.deepgram_api_key}"
```

---

## Q5. Why change the model for Hindi?

**A.** `nova-2-phonecall` is **English-only**. Sending `language=hi` with that model returns HTTP 400.

```python
def _model_for_language(language: str) -> str:
    model = settings.deepgram_model
    if language != "en" and model in _EN_ONLY_MODELS:
        return "nova-2"
    return model
```

| Call language (app) | Deepgram `language` | Model used |
|---------------------|---------------------|------------|
| English | `en` | `nova-2-phonecall` (default) |
| Hindi / Hinglish | `hi` | `nova-2` (fallback) |

`CallSession.deepgram_language` maps Hinglish → `hi` because Deepgram has no `hinglish` code.

---

## Q6. What does `send` do?

**A.** Forwards one binary audio chunk to Deepgram and stamps latency timing.

```python
async def send(self, audio: bytes) -> None:
    self.last_audio_sent_at = time.perf_counter()
    await self._ws.send(audio)
```

- Called from `pipeline.handle_audio` for every ~20 ms Twilio frame  
- `last_audio_sent_at` is used later to measure **STT latency** (audio sent → final transcript)

If STT is not connected yet, the pipeline **prebuffers** chunks (~5 s cap), then flushes them after `connect()`.

---

## Q7. What does `events()` yield, and what does it ignore?

**A.** It only yields transcription `Results`. Deepgram also sends `Metadata`, `UtteranceEnd`, etc. — those are skipped.

```python
async for raw in self._ws:
    msg = json.loads(raw)
    if msg.get("type") != "Results":
        continue
    text = msg["channel"]["alternatives"][0].get("transcript", "").strip()
    if not text:
        continue
    if msg.get("is_final"):
        yield STTEvent(type="final", text=text,
                       speech_final=bool(msg.get("speech_final")))
    else:
        yield STTEvent(type="interim", text=text)
```

| Deepgram field | Our mapping |
|----------------|-------------|
| `is_final == false` | `STTEvent(type="interim", ...)` |
| `is_final == true` | `STTEvent(type="final", ..., speech_final=...)` |
| empty transcript | skip (silence / noise) |

---

## Q8. Interim vs final vs `speech_final` — how does the pipeline use them?

**A.** This is the core turn-taking / barge-in logic in `pipeline._on_stt_event`.

### Interim → barge-in

```python
if event.type == "interim":
    if self._speak_task and not self._speak_task.done():
        self._speak_task.cancel()   # stop LLM/TTS generation
        await self._clear_audio()   # Twilio clear = stop playing buffered audio
    return
```

Caller starts talking while the agent is mid-sentence → we cut the agent off immediately. We do **not** send interims to the LLM (they’re unstable).

### Final (not speech_final) → accumulate

```python
self._utterance_parts.append(event.text)
if not event.speech_final:
    return  # wait; caller may still be talking
```

Deepgram can finalize short phrases before the full turn is done. We glue them together.

### Final + speech_final → full caller turn

```python
utterance = " ".join(self._utterance_parts).strip()
self.session.add_user_message(utterance)
# then generate_reply → TTS
```

Only then does the LLM see the caller’s text.

### Mental model

```
interim     = "someone is speaking"     → interrupt agent if needed
final       = "this phrase is locked"   → append to buffer
speech_final= "they're done for now"    → run the agent
```

---

## Q9. What is endpointing?

**A.** Detecting when the caller has **finished their turn** (usually via a short silence), not just when a word ended.

- `endpointing=300` ≈ wait ~300 ms of silence before marking `speech_final`  
- Without it, you’d either:
  - cut the caller off mid-thought, or  
  - wait forever for a perfect “end”

Voice agents live or die on good endpointing + barge-in together.

---

## Q10. How does `close` work?

**A.** Graceful Deepgram shutdown:

```python
await self._ws.send(json.dumps({"type": "CloseStream"}))
await self._ws.close()
```

Called from `pipeline._cleanup` when the call ends or the pipeline fails. Errors are swallowed so teardown never crashes the gateway.

---

## Q11. Walk through audio → text for one turn

1. Twilio sends mulaw frame → `handle_audio` → `stt.send(bytes)`.  
2. Deepgram streams back interim `"I can pay..."`.  
3. If agent was speaking → cancel speak + `clear_audio` (barge-in).  
4. More audio → final phrase(s) appended to `_utterance_parts`.  
5. Silence ~300 ms → `speech_final=True`.  
6. Pipeline joins parts → `"I can pay ten thousand by August tenth."`  
7. `add_user_message` → transcript + LLM history.  
8. `generate_reply` → model may structure tool args → TTS speaks.

That’s the bridge from **NLP speech** to the **structured tool args** story in the LLM folder.

---

## Q12. What should you say in an interview about this folder?

**Short version**

> STT is a thin Deepgram WebSocket client behind an `STTProvider` interface. We stream Twilio’s native mulaw 8 kHz audio with no resampling, enable interim results for barge-in, and use Deepgram endpointing (`speech_final`) to decide when a caller turn is complete. Non-English calls fall back from `nova-2-phonecall` to `nova-2` because the phone model is English-only.

**Deeper if asked about latency**

> We timestamp `last_audio_sent_at` on every send and mark STT done when we get the final turn, so the dashboard can show per-turn STT latency separately from LLM and TTS.

**Deeper if asked about barge-in**

> Interims never go to the LLM. They only cancel in-flight speech and clear Twilio’s audio buffer so the caller isn’t talking over the bot.

---

## Quick reference — mental model

```
base.py         →  STTEvent + STTProvider contract
deepgram_stt.py →  WebSocket audio in, STTEvents out
```

```
send(audio)     =  push mulaw frame to Deepgram
events()        =  interim | final (+ speech_final)
pipeline        =  interim→barge-in, speech_final→LLM turn
```

```
Phone audio  →  STT  →  text  →  LLM  →  sentences  →  TTS  →  Phone audio
```
