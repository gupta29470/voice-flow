from dataclasses import dataclass


@dataclass
class Voice:
    provider: str
    id: str
    name: str
    description: str = ""
    language: str = "en"  # ISO 639-1, e.g. "en" or "hi"


class TTSProvider:
    name: str = "base"

    async def stream(self, text: str, voice_id: str, language: str = "en"):
        """Async generator: yield mulaw @ 8kHz audio chunks for `text`.

        Chunks flow straight to Twilio — the earlier the first chunk, the
        lower the perceived latency (time-to-first-audio, TTFB)."""
        raise NotImplementedError

    async def list_voices(self) -> list[Voice]:
        raise NotImplementedError

def get_provider(name: str) -> TTSProvider:
    """Factory. Imports are inside the function so a broken/missing
    provider dependency can never break the other provider."""
    from app.tts.cartesia_tts import CartesiaTTS
    from app.tts.elevenlabs_tts import ElevenLabsTTS

    providers = {"cartesia": CartesiaTTS, "elevenlabs": ElevenLabsTTS}
    if name not in providers:
        raise ValueError(f"Unknown TTS provider: {name}")
    return providers[name]()


def tts_language(call_language: str) -> str:
    """Map call language (en/hi/hinglish) to a Cartesia/TTS language code."""
    return "en" if call_language == "en" else "hi"
