import base64
import json
import uuid

import httpx
import websockets

from app.config import settings
from app.tts.base import TTSProvider, Voice

WS_URL = ("wss://api.cartesia.ai/tts/websocket"
          "?api_key={key}&cartesia_version=2025-04-16")
VOICES_URL = "https://api.cartesia.ai/voices"
# Fetch a small set of English + Hindi voices for the dashboard picker.
_VOICE_LANGS = ("en", "hi")
_VOICES_PER_LANG = 8

class CartesiaTTS(TTSProvider):
    name = "cartesia"

    async def stream(self, text, voice_id: str, language: str = "en"):
        async with websockets.connect(
            WS_URL.format(key=settings.cartesia_api_key)
        ) as ws:
            await ws.send(json.dumps({
                "model_id": settings.cartesia_model,
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "language": language,
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_mulaw",   # exactly what Twilio plays
                    "sample_rate": 8000,
                },
                "context_id": uuid.uuid4().hex,
                "continue": False,             # this request is complete
            }))
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "chunk" and msg.get("data"):
                    yield base64.b64decode(msg["data"])
                elif msg.get("type") == "done":
                    break
                elif msg.get("type") == "error":
                    raise RuntimeError(f"Cartesia error: {msg}")

    async def list_voices(self) -> list[Voice]:
        voices: list[Voice] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for lang in _VOICE_LANGS:
                resp = await client.get(
                    VOICES_URL,
                    params={"language": lang, "limit": _VOICES_PER_LANG},
                    headers={
                        "X-API-Key": settings.cartesia_api_key,
                        "Cartesia-Version": "2025-04-16",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                # Bare list or {"data": [...]} — accept either.
                items = data.get("data", []) if isinstance(data, dict) else data
                for v in items:
                    voices.append(Voice(
                        provider=self.name,
                        id=v["id"],
                        name=v.get("name", v["id"]),
                        description=v.get("description") or v.get("tagline") or "",
                        language=v.get("language") or lang,
                    ))
        return voices
