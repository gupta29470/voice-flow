import json
import re

from openai import AsyncOpenAI

from app import storage
from app.config import settings
from app.llm.tools import TOOLS_SCHEMAS, execute_tool

_client = AsyncOpenAI(api_key=settings.llm_api_key,
                      base_url=settings.llm_base_url)

# A sentence ends with . ! or ? followed by whitespace. Splitting on this
# keeps the sentence's punctuation attached to the sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

MAX_TOOL_LOOPS = 3

def _split_sentences(buffer: str):
    """Split a streaming buffer into (complete_sentences, remainder).

    The last fragment may be an unfinished sentence — hold it back until
    more tokens arrive."""
    parts = _SENTENCE_END.split(buffer)
    if len(parts) == 1:
        return [], buffer
    return parts[:-1], parts[-1]

async def generate_reply(session):
    """Async generator: yields the agent's reply one sentence at a time.

    Tool calls are handled transparently inside the loop — the caller of
    this generator only ever sees speakable sentences.

    Message history is updated inside the loop. The transcript gets one
    agent row with all spoken text for the turn. If the generator is
    cancelled mid-stream (barge-in), any unspoken-to-history audio is
    synced in finally so the next turn still has context.
    """
    tools = [TOOLS_SCHEMAS[name] for name in session.workflow.tools]
    full_reply = ""
    # Spoken text already placed into session.messages this turn.
    committed_speech = ""
    try:
        for _ in range(MAX_TOOL_LOOPS):
            stream = await _client.chat.completions.create(
                model=settings.llm_model,
                messages=session.messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
                max_tokens=300,        # short spoken replies
                stream=True,
            )

            buffer = ""
            content_so_far = ""
            tool_calls: dict[int, dict] = {}
            finish_reason = None

            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                if delta and delta.content:
                    buffer += delta.content
                    content_so_far += delta.content
                    sentences, buffer = _split_sentences(buffer)
                    for sentence in sentences:
                        if sentence.strip():
                            full_reply += sentence + " "
                            yield sentence.strip()

                if delta and delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        slot = tool_calls.setdefault(
                            tool_call.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if tool_call.id:
                            slot["id"] += tool_call.id
                        if tool_call.function and tool_call.function.name:
                            slot["name"] += tool_call.function.name
                        if tool_call.function and tool_call.function.arguments:
                            slot["arguments"] += tool_call.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            # Flush leftover speech before tools so goodbye text is heard.
            if buffer.strip():
                full_reply += buffer + " "
                yield buffer.strip()
                buffer = ""

            if finish_reason == "tool_calls" and tool_calls:
                ordered = [tool_calls[index] for index in sorted(tool_calls)]
                session.messages.append({
                    "role": "assistant",
                    "content": content_so_far or None,
                    "tool_calls": [{
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {"name": tool_call["name"],
                                     "arguments": tool_call["arguments"]},
                    } for tool_call in ordered],
                })
                if content_so_far.strip():
                    committed_speech = (
                        f"{committed_speech} {content_so_far}".strip()
                        if committed_speech else content_so_far.strip()
                    )

                for tool_call in ordered:
                    try:
                        args = json.loads(tool_call["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    result = execute_tool(session, tool_call["name"], args)
                    session.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_call["name"],
                        "content": result,
                    })

                # Hangup / transfer: speech should already have been streamed
                # before the tool (goodbye / "connecting you now").
                if session.end_requested or session.transfer_requested:
                    break
                continue

            # Plain speech turn — record once in the LLM history.
            if content_so_far.strip():
                session.messages.append({
                    "role": "assistant",
                    "content": content_so_far.strip(),
                })
                committed_speech = (
                    f"{committed_speech} {content_so_far}".strip()
                    if committed_speech else content_so_far.strip()
                )
            break

    finally:
        text = full_reply.strip()
        if text:
            storage.add_transcript(session.call_id, "agent", text)
            # Barge-in can cancel mid-stream before we append to messages.
            if not committed_speech:
                session.messages.append({"role": "assistant", "content": text})
            elif text.startswith(committed_speech) and text != committed_speech:
                rest = text[len(committed_speech):].strip()
                if rest:
                    session.messages.append({"role": "assistant", "content": rest})
