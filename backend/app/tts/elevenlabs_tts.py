import base64
import json

import httpx
import websockets

from app.config import settings
from app.tts.base import TTSProvider, Voice

WS_URL = ("wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
          "?model_id={model}&output_format=ulaw_8000")
VOICES_URL = "https://api.elevenlabs.io/v1/voices"

class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"

    async def stream(self, text: str, voice_id: str):
        url = WS_URL.format(voice_id=voice_id,
                            model=settings.elevenlabs_model)

        async with websockets.connect(url) as ws:
            # 1. Handshake: an initial space + config + API key.
            await ws.send(json.dumps({
                "text": " ",
                "xi_api_key": settings.elevenlabs_api_key,
                "voice_settings": {"stability": 0.5,
                                   "similarity_boost": 0.75},
            }))

            # 2. The text to speak. try_trigger_generation says "don't
            #    buffer, start synthesizing now".
            await ws.send(json.dumps({
                "text": text,
                "try_trigger_generation": True,
            }))

            # 3. Empty string = end of input: flush and finish.
            await ws.send(json.dumps({"text": ""}))

            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("audio"):
                    yield base64.b64decode(msg["audio"])
                if msg.get("isFinal"):
                    break

    async def list_voices(self) -> list[Voice]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                VOICES_URL,
                headers={"xi-api-key": settings.elevenlabs_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            Voice(provider=self.name, id=v["voice_id"],
                  name=v.get("name", ""),
                  description=(v.get("labels") or {}).get("description", "")
                  or "")
            for v in data.get("voices", [])[:8]
        ]