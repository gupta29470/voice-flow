import asyncio
import logging
import time

from app import storage
from app.llm.agent import generate_reply
from app.metrics import TurnTimer
from app.stt.deepgram_stt import DeepgramSTT
from app.tts.base import get_provider, tts_language

log = logging.getLogger("pipeline")


class CallPipeline:
    """One instance = one phone call. The media stream gateway (chapter 7)
    constructs this, calls start(), and feeds it audio via handle_audio().

    Callables are injected rather than imported — the pipeline doesn't
    know Twilio exists. It just knows "send audio", "clear audio", "hang up".
    """

    def __init__(self, session, send_audio, clear_audio, hangup, transfer):
        self.session = session
        self._send_audio = send_audio
        self._clear_audio = clear_audio
        self._hangup = hangup
        self._transfer = transfer

        self.stt = DeepgramSTT(language=session.deepgram_language)
        self.tts = get_provider(session.tts_provider)

        self._run_task: asyncio.Task | None = None
        self._speak_task: asyncio.Task | None = None
        self._utterance_parts: list[str] = []
        self._stt_ready = False
        self._prebuffer: list[bytes] = [] # audio arriving before STT connects
        self._failed = False

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        self._run_task = asyncio.create_task(self.run())

    async def handle_audio(self, chunk: bytes) -> None:
        """Called by the gateway for every ~20ms Twilio media frame."""
        if self._stt_ready:
            await self.stt.send(chunk)
        elif len(self._prebuffer) < 250: # ~5s cap, then drop
            self._prebuffer.append(chunk)

    async def shutdown(self) -> None:
        """Called by the gateway when the WebSocket ends."""
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass

    # ── main loop ────────────────────────────────────────────────────────
    async def run(self) -> None:
        try:
            await self.stt.connect()
            self._stt_ready = True
            for chunk in self._prebuffer:
                await self.stt.send(chunk)
            self._prebuffer = []

            # The agent always speaks first — it made the call.
            if self.session.language == "en":
                line = self.session.opening_line()
                self.session.add_assistant_message(line)
                await self._speak_text(line)
            else:
                # Non-English call: the hardcoded English opening line would be
                # wrong — let the LLM open in the right language instead.
                self.session.messages.append({
                    "role": "user",
                    "content": (
                        "[The callee has answered. Greet them and introduce "
                        "yourself as your instructions say, in the required "
                        "language.]"
                    ),
                })

                async for sentence in generate_reply(self.session):
                    await self._speak_text(sentence)

            async for event in self.stt.events():
                await self._on_stt_event(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failed = True
            log.exception("pipeline error on call %s", self.session.call_id)
        finally:
            await self._cleanup()


    async def _cleanup(self) -> None:
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()

            try:
                await self._speak_task
            except asyncio.CancelledError:
                pass

        await self.stt.close()
        storage.end_call_record(
            self.session.call_id,
            status="failed" if self._failed else "completed"
        )

    # ── turn handling ────────────────────────────────────────────────────
    async def _on_stt_event(self, event) -> None:
        if self.session.end_requested or self.session.transfer_requested:
            return

        if event.type == "interim":
            # BARGE-IN: caller started talking while the agent is speaking.
            if self._speak_task and not self._speak_task.done():
                self._speak_task.cancel()
                await self._clear_audio()
            return

        # Final transcript for a chunk of speech. Accumulate until
        # endpointing declares the turn complete.
        self._utterance_parts.append(event.text)
        if not event.speech_final:
            return

        utterance = " ".join(self._utterance_parts).strip()
        self._utterance_parts = []
        if not utterance:
            return

        # A new caller turn cancels any still-running agent reply so we
        # don't race two generate_reply loops on the same message list.
        if self._speak_task and not self._speak_task.done():
            self._speak_task.cancel()
            await self._clear_audio()
            try:
                await self._speak_task
            except asyncio.CancelledError:
                pass

        self.session.turn += 1
        self.session.add_user_message(utterance)

        timer = TurnTimer(self.session.call_id, self.session.turn)
        timer.mark("final_transcript")
        if self.stt.last_audio_sent_at:
            timer.set_mark("audio_sent", self.stt.last_audio_sent_at)
            timer.stt_done()

        self._speak_task = asyncio.create_task(self._respond(timer))

    # ── speaking ─────────────────────────────────────────────────────────
    async def _respond(self, timer: TurnTimer) -> None:
        """One full agent turn: LLM reply, spoken sentence by sentence."""
        try:
            timer.mark("llm_start")
            first_sentence = True
            turn_timer: TurnTimer | None = timer
            spoken_bytes = 0
            first_audio_at: float | None = None

            async for sentence in generate_reply(self.session):
                if first_sentence:
                    timer.llm_first_sentence()
                    first_sentence = False
                if first_audio_at is None:
                    first_audio_at = time.perf_counter()
                spoken_bytes += await self._speak_text(sentence, turn_timer)
                turn_timer = None

            if self.session.transfer_requested or self.session.end_requested:
                # mulaw @ 8kHz = 8000 bytes/sec of audio. TTS streams faster
                # than real-time, so Twilio is still playing buffered audio
                # after we finish sending. Wait exactly until the buffer
                # drains (+0.3s margin) — no sooner (cuts the goodbye),
                # no later (dead air).
                remaining = (spoken_bytes / 8000) - (
                    time.perf_counter() - (first_audio_at or time.perf_counter()))
                await asyncio.sleep(max(0.2, remaining + 0.3))
                if self.session.transfer_requested:
                    log.info("transfer requested — transferring call %s",
                             self.session.call_id)
                    await self._transfer()
                else:
                    log.info("end_call requested — hanging up call %s",
                             self.session.call_id)
                    await self._hangup()

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("response failed")
        finally:
            timer.save()

    async def _speak_text(self, text: str, timer: TurnTimer | None = None) -> int:
        """Stream one piece of text through TTS and out to the caller.
        Returns the number of audio bytes sent."""
        sent = 0
        try:
            if timer:
                timer.mark("tts_start")
            lang = tts_language(self.session.language)
            async for chunk in self.tts.stream(
                text, self.session.voice_id, language=lang
            ):
                if timer and timer.metrics.tts_ms is None:
                    timer.tts_first_audio()
                if timer and timer.metrics.e2e_ms is None:
                    timer.first_audio_out()
                await self._send_audio(chunk)
                sent += len(chunk)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("tts failed")
        return sent
