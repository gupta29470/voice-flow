from dataclasses import dataclass

@dataclass
class STTEvent:
    type: str # "interim" or "final"
    text: str
    speech_final: bool = False # endpointing fired: caller's turn is over

class STTProvider:
    async def connect(self) -> None:
        raise NotImplementedError

    async def send(self, audio: bytes) -> None:
        """Push one chunk of mulaw @ 8kHz audio."""
        raise NotImplementedError

    def events(self):
        """Async generator yielding STTEvent for the life of the call."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    