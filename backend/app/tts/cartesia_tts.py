import base64
import json
import logging
import uuid

import httpx
import websockets

from app.config import settings
from app.tts.base import TTSProvider, Voice

log = logging.getLogger("tts")

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
        """Every voice this account offers, once per voice.

        Two things the first version got wrong, both found by a review pass:

        * ONE language's request failing aborted the whole list. A 4xx/5xx or a timeout on the
          Hindi call lost the English voices too, so the picker claimed the account had none.
          Each language is fetched independently now, and a failure is logged and skipped.
        * The same voice comes back for both `en` and `hi`, and appending per language listed it
          twice. Deduplicated by id, first language wins, so the picker cannot offer one voice
          twice under two different languages.
        """
        # Keyed by voice id: insertion order is preserved, and the first language that returns a
        # voice wins. A dict rather than "list + a seen set" because that is exactly the shape of
        # the thing being collected.
        found: dict[str, Voice] = {}
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=15) as client:
            for lang in _VOICE_LANGS:
                try:
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
                except (httpx.HTTPError, ValueError) as exc:
                    # `ValueError` covers a 200 whose body is not JSON: that is this language
                    # failing, not the account having no voices.
                    log.warning("cartesia_voice_list_failed lang=%s error=%s", lang, exc)
                    last_error = exc
                    continue
                # Bare list or {"data": [...]} — accept either.
                items = data.get("data", []) if isinstance(data, dict) else data
                for v in items:
                    found.setdefault(v["id"], Voice(
                        provider=self.name,
                        id=v["id"],
                        name=v.get("name", v["id"]),
                        description=v.get("description") or v.get("tagline") or "",
                        language=v.get("language") or lang,
                    ))
        if not found and last_error is not None:
            # EVERY language failed, and that is not the same fact as "this account has no voices".
            # Reporting it as an empty list is what turned an invalid key or an outage into a
            # cheerful "no voices for this provider" — a review flagged it, and the caller loses the
            # distinction it needs to tell the user what to fix.
            raise last_error
        return list(found.values())
