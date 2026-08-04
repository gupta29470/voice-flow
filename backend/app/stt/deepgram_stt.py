import json
import time

import websockets

from app.config import settings
from app.stt.base import STTEvent, STTProvider

DEEPGRAM_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?encoding=mulaw&sample_rate=8000&channels=1"
    "&model={model}&interim_results=true&endpointing=300&smart_format=true"
)

class DeepgramSTT(STTProvider):
    def __init__(self, language: str = "en") -> None:
        self._ws = None
        self.language = language
        self.last_audio_sent_at: float | None = None

    async def connect(self) -> None:
        url = (DEEPGRAM_URL.format(model=settings.deepgram_model)
               + f"&language={self.language}")
        self._ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Token {settings.deepgram_api_key}"
            },
        )

    async def send(self, audio: bytes) -> None:
        self.last_audio_sent_at = time.perf_counter()
        await self._ws.send(audio)

    async def events(self):
        async for raw in self._ws:
            msg = json.loads(raw)
            # Deepgram also sends Metadata and UtteranceEnd messages —
            # we only care about transcription Results.
            if msg.get("type") != "Results":
                continue
            alt = msg["channel"]["alternatives"][0]
            text = alt.get("transcript", "").strip()
            if not text:
                continue
            if msg.get("is_final"):
                yield STTEvent(
                    type="final",
                    text=text,
                    speech_final=bool(msg.get("speech_final")),
                )
            else:
                yield STTEvent(type="interim", text=text)


    async def close(self) -> None:
        if self._ws is None:
            return
        try:
            # Politely tell Deepgram the stream is over, then hang up.
            await self._ws.send(json.dumps({"type": "CloseStream"}))
            await self._ws.close()
        except Exception:
            pass