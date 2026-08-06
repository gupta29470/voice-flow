# VoiceFlow Q&A guide

This document explains `backend/app/llm/` so you can read the code, walk someone through it, and answer interview-style questions.

**Files in this folder**

| File | Role |
|------|------|
| `agent.py` | Talks to the LLM; streams **sentences**; runs tools |
| `tools.py` | Tool schemas (what the model can call) + Python handlers |
| `workflows.py` | Call types (loan recovery, EMI, banking, sales) as config |

**How this fits the call pipeline**

```
Caller speaks → Deepgram STT → text
                              ↓
                    session.add_user_message(text)
                              ↓
                    generate_reply(session)  ← you are here
                              ↓
                    yields sentences one by one
                              ↓
                    TTS speaks each sentence → Twilio → phone
```

The pipeline (`pipeline.py`) never sees raw LLM tokens or tool JSON. It only gets speakable sentences from `generate_reply`.

---

## Q1. What does `_split_sentences` do?

**A.** It turns a growing stream of LLM text into **complete sentences** vs **leftover unfinished text**.

Signature idea:

```python
complete_sentences, remainder = _split_sentences(buffer)
```

- **complete_sentences** — ready to send to TTS right now  
- **remainder** — incomplete fragment; keep buffering until more tokens arrive  

### Why it exists

LLMs stream tokens like:

```
"Thanks," → " Rahul." → " Your" → " EMI" → " is" → " due" → " tomorrow."
```

If you waited for the **whole** reply before speaking, the caller would hear a long silence.  
If you spoke **every token**, TTS would get tiny scraps (`"Your"`, `" EMI"`) and sound broken.

So we speak **sentence by sentence**: as soon as we see `.` / `!` / `?` followed by whitespace, that sentence is done.

### The regex

```python
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
```

| Piece | Meaning |
|-------|---------|
| `(?<=[.!?])` | Lookbehind: previous char was `.`, `!`, or `?` |
| `\s+` | Then one or more spaces / newlines — **this** is what we split on |

Punctuation stays on the sentence (lookbehind does not consume it). The whitespace between sentences is discarded by `split`.

### Examples

**Example 1 — unfinished sentence (hold back)**

```python
_split_sentences("Thanks Rahul, your EMI is")
# → ([], "Thanks Rahul, your EMI is")
```

No `.!?` + space yet → nothing to speak; keep the whole string as remainder.

**Example 2 — one complete sentence + remainder**

```python
_split_sentences("Thanks Rahul. Your EMI is")
# → (["Thanks Rahul."], "Your EMI is")
```

`"Thanks Rahul."` can go to TTS. `"Your EMI is"` waits for more tokens.

**Example 3 — two complete sentences**

```python
_split_sentences("Hi. How are you? I am Priya.")
# → (["Hi.", "How are you?"], "I am Priya.")
```

Wait — the last part has a period but **no trailing whitespace after it**, so it is still the remainder. When the stream ends, `generate_reply` **flushes** that remainder anyway.

After more streaming adds a space or the stream finishes:

```python
# Mid-stream with trailing space after last sentence:
_split_sentences("Hi. How are you? ")
# → (["Hi.", "How are you?"], "")
```

**Example 4 — streaming over time (how the agent uses it)**

| Tokens arrive | `buffer` after append | `_split_sentences` result | Yielded to TTS |
|---------------|----------------------|---------------------------|----------------|
| `"Thanks,"` | `Thanks,` | `[], "Thanks,"` | — |
| `" Rahul."` | `Thanks, Rahul.` | `[], "Thanks, Rahul."` | — (no space after `.` yet) |
| `" Your"` | `Thanks, Rahul. Your` | `["Thanks, Rahul."], "Your"` | `"Thanks, Rahul."` |
| `" EMI is due tomorrow."` | `Your EMI is due tomorrow.` | `[], "Your EMI is due tomorrow."` | — |
| stream ends | flush remainder | | `"Your EMI is due tomorrow."` |

### Edge cases to mention

- Abbreviations like `"Mr. Sharma"` can falsely split if followed by a space — acceptable for short voice replies; prompts tell the model to speak simply.
- No sentence-ending punctuation → entire reply is flushed once at the end of the stream (still one yield).

---

## Q2. What is `delta` and `delta.content` exactly?

**A.** In the streaming chat API (`stream=True`), each chunk is a **partial update** to the assistant message — not the full reply.

In `generate_reply`:

```python
choice = chunk.choices[0]
delta = choice.delta          # this chunk's partial message update
if delta and delta.content:   # only if this chunk carries text
    buffer += delta.content
```

| Thing | Meaning |
|--------|---------|
| **`delta`** | “What changed in the assistant message in **this** chunk.” Can include `content`, and/or `tool_calls`, sometimes `role` on the first chunk. |
| **`delta.content`** | The next **text fragment** of the reply (a few characters/words). Not a full sentence. Can be `None` / missing when the chunk is only about tools or finish. |

So: **`delta` = the patch object**; **`delta.content` = the speakable-text part of that patch** (if any).

### Example chunk shapes

Early text chunk:

```json
{
  "choices": [
    {
      "delta": {
        "role": "assistant",
        "content": "Thanks"
      },
      "finish_reason": null
    }
  ]
}
```

Later text chunk:

```json
{
  "choices": [
    {
      "delta": {
        "content": ", Rahul."
      },
      "finish_reason": null
    }
  ]
}
```

Eventually a chunk arrives with `"finish_reason": "stop"` or `"tool_calls"`.

### Why the code checks both `delta` and `delta.content`

```python
if delta and delta.content:
    buffer += delta.content
```

- Some chunks have `delta` but **no** text (tool-call pieces, or empty keepalives).
- Tool streaming uses `delta.tool_calls` instead of `delta.content`.
- You accumulate `delta.content` into `buffer`, then `_split_sentences` decides when a full sentence is ready for TTS.

### Tiny mental model

```
Full reply the model "wants" to say:
  "Thanks, Rahul. Your EMI is due."

Streamed as deltas:
  content="Thanks"     → buffer = "Thanks"
  content=", Rahul."   → buffer = "Thanks, Rahul."
  content=" Your"      → buffer = "Thanks, Rahul. Your"  → yield "Thanks, Rahul."
  content=" EMI is due." → ...
```

`delta` is one of those patches; `delta.content` is the string inside it.

---

## Q3. What does `generate_reply` do? (detailed)

**A.** `generate_reply(session)` is an **async generator** that:

1. Calls the LLM with the call’s chat history + allowed tools  
2. Streams the response  
3. Yields **one speakable sentence at a time**  
4. If the model calls tools, runs them, appends results to history, and may loop again  
5. Updates `session.messages` and the transcript so the next turn has context  
6. On barge-in cancel, still syncs whatever was spoken into history in `finally`

Callers (pipeline) only do:

```python
async for sentence in generate_reply(self.session):
    await self._speak_text(sentence)  # TTS
```

They never handle tools or token buffering.

### High-level loop

```
for up to MAX_TOOL_LOOPS (3):
    stream LLM(messages, tools)

    for each chunk:
        if text tokens → buffer → split sentences → yield each
        if tool_call deltas → assemble tool name/args by index

    flush leftover buffer as one last sentence

    if finish_reason == "tool_calls":
        append assistant message (content + tool_calls)
        execute each tool → append role:"tool" results
        if hangup or transfer → break
        else → continue loop (LLM sees tool results, speaks again)
    else:
        append plain assistant message
        break
```

### Important local variables

| Variable | Meaning |
|----------|---------|
| `buffer` | Text not yet confirmed as a complete sentence |
| `content_so_far` | All text content from **this** LLM stream |
| `tool_calls` | Assembled tool calls keyed by `index` (streaming fragments) |
| `full_reply` | Everything yielded this turn (for transcript) |
| `committed_speech` | Text already written into `session.messages` this turn |
| `finish_reason` | `"stop"` (normal) or `"tool_calls"` |

### Path A — plain speech (no tools)

**Caller said:** `"Yes, this is Rahul."`

1. Pipeline already appended that as a `user` message.  
2. LLM streams: `"Thanks, Rahul. I'm calling about your overdue loan of forty-five thousand rupees. What has been getting in the way?"`  
3. `_split_sentences` yields three sentences → TTS plays them quickly, one after another.  
4. `finish_reason == "stop"` → append one assistant message with full content → `break`.  
5. `finally`: write one agent transcript row with all spoken text.

### Path B — speech + tool (e.g. promise to pay)

**Caller said:** `"I can pay 10000 by August 10."`

1. LLM may stream: `"Perfect, I've noted that."` then emit a `log_promise_to_pay` tool call.  
2. Complete sentences are yielded **before** tools run (goodbye / confirm text is heard first).  
3. Leftover buffer is flushed.  
4. Because `finish_reason == "tool_calls"`:
   - Append assistant message with `content` + `tool_calls`
   - `execute_tool(session, "log_promise_to_pay", {...})` → returns a string for the model  
   - Append `role: "tool"` message with that result  
5. If not `end_requested` / `transfer_requested`, **loop again**: second LLM call sees the tool result and may say `"You're all set. I'll end the call now."` then call `end_call`.

### Path C — hangup / transfer

Tools `end_call` and `escalate_to_human` set flags on the session:

- `session.end_requested = True`
- `session.transfer_requested = True`

After those tools run, the loop **breaks** so we don’t keep chatting. Speech (goodbye / “connecting you”) should already have been streamed in the same turn **before** the tool.

### Tool-call streaming (why a dict by index?)

OpenAI-style streams send tool calls in pieces:

```
delta.tool_calls[0].id = "call_abc"
delta.tool_calls[0].function.name = "log_promise"
delta.tool_calls[0].function.arguments = "{\"amount\":"
... later ...
delta.tool_calls[0].function.arguments = "10000}"
```

Code accumulates into:

```python
tool_calls[index] = {"id": "...", "name": "...", "arguments": "..."}
```

Then `json.loads` the arguments and calls `execute_tool`.

### Barge-in and the `finally` block

If the caller interrupts, the pipeline **cancels** the `generate_reply` task mid-stream.

`finally` still runs:

1. Save spoken text to the transcript (`storage.add_transcript`).  
2. If nothing was committed to `session.messages` yet, append the spoken text as assistant.  
3. If some text was committed (e.g. before a tool) but more was spoken after, append only the **rest**.

Without this, the next turn’s LLM would not know what the agent already said aloud.

### Why `max_tokens=300`?

Phone replies should stay short. Long essays hurt latency and conversation feel.

### Why `MAX_TOOL_LOOPS = 3`?

Stops infinite tool → reply → tool loops (bugs / model thrashing). Typical call needs 1–2 tool rounds per turn.

---

## Q4. What is `agent.py` responsible for overall?

**A.** It is the **brain adapter** between:

- **CallSession** (messages, workflow, flags), and  
- **the LLM provider** (Grok by default, OpenAI-compatible client).

It does **not** own STT, TTS, or Twilio. It only:

- Streams chat completions  
- Sentence-splits for low time-to-first-audio  
- Runs tools via `execute_tool`  
- Keeps message history + transcript consistent, including after cancel  

---

## Q5. What does `tools.py` contain?

**A.** Two layers:

1. **`TOOLS_SCHEMAS`** — JSON schemas the LLM sees (name, description, parameters).  
2. **`HANDLERS` + `execute_tool`** — real Python that runs when the model calls a tool.

### Available tools (summary)

| Tool | Purpose | Side effects |
|------|---------|--------------|
| `lookup_loan_details` | Return loan demo data from call context | None (read-only) |
| `log_promise_to_pay` | Record payment promise | `session.set_capture("promise_to_pay", …)` |
| `qualify_lead` | Record sales interest | `session.set_capture("lead_qualified", …)` |
| `lookup_balance` | Demo balance JSON | None |
| `lookup_branch` | Demo branch string | None |
| `escalate_to_human` | Start human handoff | capture + `transfer_requested = True` |
| `end_call` | Hang up | capture + `end_requested = True` (with safety gate) |

### How `execute_tool` works

```python
result = execute_tool(session, "log_promise_to_pay",
                      {"amount": 10000, "pay_by_date": "2026-08-10"})
# → string the model will read on the next loop iteration
```

Unknown tool names or bad arguments return an error string instead of crashing the call.

---

## Q6. Why does `end_call` sometimes refuse to hang up?

**A.** Safety gate for premature hangups.

If:

- `session.turn <= 1`, and  
- there is no outcome yet, and  
- reason is **not** an early-exit reason (`wrong_person`, `caller_requested`, …),  

then `_end_call` **rejects** the hangup and tells the model to continue with the next goal.

**Example**

Caller: `"Yes."` (just confirmed identity)  
Bad model behavior: immediately call `end_call(reason="completed")`  
Tool returns: *"Call not ended — continue with the next unfinished goal…"*  
Call stays alive; next LLM loop (or turn) can ask about the loan.

Early exits still work on turn 1 (wrong person, busy, not interested, etc.).

---

## Q7. What does a tool “return value” mean on a phone call?

**A.** The return string is **not** spoken to the caller directly.

It is appended as:

```python
{"role": "tool", "tool_call_id": "...", "name": "...", "content": result}
```

On the next LLM iteration, the model **reads** that result and chooses what to say out loud (which then goes through sentence streaming → TTS).

Exception in spirit: handlers for hangup/transfer tell the model not to keep talking because the pipeline will end/transfer the call.

---

## Q8. What are workflows (`workflows.py`)?

**A.** A workflow is a **config object** for one kind of outbound call — not a separate code path.

```python
@dataclass
class WorkflowConfig:
    id: str
    name: str
    description: str
    fields: list[WorkflowField]   # dashboard form inputs
    system_prompt: str            # agent personality + goals
    opening_line: str             # first words when callee answers
    tools: list[str]              # whitelist of tool names
```

### The four demos

| ID | Agent | Goal in one line |
|----|--------|------------------|
| `loan_recovery` | Priya | Confirm identity → discuss overdue → `log_promise_to_pay` |
| `emi_reminder` | Priya | Remind upcoming EMI → confirm on-time pay |
| `banking_info` | Maya | Answer balance/branch via tools |
| `sales` | Arjun | Qualify lead → `qualify_lead` |

### Placeholders

Form fields like `borrower_name` become `{borrower_name}` in the prompt and opening line.  
`CallSession._render()` fills them from `context` when the call starts.

### `COMMON_RULES`

Shared phone etiquette (short sentences, no markdown, one question per turn, when to escalate / end). Injected into every system prompt so you don’t repeat yourself four times.

### Language instructions

`LANGUAGE_INSTRUCTIONS` (`en` / `hi` / `hinglish`) are appended to the system prompt by `CallSession` so the same workflow can run in different spoken styles.

---

## Q9. How does the LLM know which tools it may use?

**A.** Per workflow whitelist.

```python
# agent.py
tools = [TOOLS_SCHEMAS[name] for name in session.workflow.tools]
```

Example: `emi_reminder` only gets `escalate_to_human` and `end_call` — it cannot call `log_promise_to_pay` even though that schema exists in `tools.py`.

---

## Q10. Walk through one full turn end-to-end

**Workflow:** loan recovery  
**Context:** Rahul Sharma, ₹45,000, 30 days overdue  

1. Callee answers → pipeline speaks `opening_line` (no LLM yet).  
2. Caller: `"Yes, speaking."` → STT → `add_user_message`.  
3. `generate_reply`:
   - LLM sees system prompt + opening context + user text  
   - Streams: `"Thanks, Rahul. I'm calling about forty-five thousand rupees that is thirty days overdue. What has been getting in the way of payment?"`  
   - Yields 3 sentences → TTS → phone  
   - Appends assistant message; transcript updated  
4. Caller answers with a hardship story → next turn, same loop.  
5. Later, caller commits to pay → model calls `log_promise_to_pay` → capture stored for dashboard → model confirms → `end_call` → `session.end_requested` → Twilio hangup.

---

## Q11. Why sentence streaming instead of waiting for the full completion?

**A.** Latency.

| Approach | Time until caller hears something |
|----------|-------------------------------------|
| Wait for full LLM reply | STT + full LLM + full TTS |
| Sentence streaming | STT + time-to-**first sentence** + TTS |

First audio can start after the first `.` / `!` / `?`, while later sentences are still being generated. That is critical for natural phone feel.

---

## Q12. What should you say in an interview about this folder?

**Short version**

> The LLM layer is a cascaded agent: OpenAI-compatible chat with tool calling. I stream tokens, split on sentence boundaries so TTS can start early, and run tools inside the generator so the telephony pipeline only receives speakable text. Workflows are config — prompts, form fields, opening line, and tool whitelist — so adding a new call type doesn’t mean rewriting the pipeline.

**Deeper if asked about barge-in**

> If the user interrupts, we cancel the reply generator. A `finally` block still writes whatever was already spoken into the transcript and message history so the model doesn’t lose context on the next turn.

**Deeper if asked about tools**

> Schemas are what the model sees; handlers mutate the session (captures, end/transfer flags). `end_call` has a small safety gate against hanging up on the first “yes.”

---

## Quick reference — mental model

```
workflows.py  →  "Who is the agent and what may it do?"
tools.py      →  "How do actions become real side effects?"
agent.py      →  "How do we turn LLM streams into spoken turns?"
```

```
_split_sentences  =  buffer → (ready for TTS, keep waiting)
generate_reply    =  LLM stream + tools loop → yield sentences
```
