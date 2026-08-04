import time
from dataclasses import dataclass

from app import storage

@dataclass
class TurnMetrics:
    stt_ms: float | None = None
    llm_ms: float | None = None
    tts_ms: float | None = None
    e2e_ms: float | None = None

class TurnTimer:
    """One instance per caller turn. Mark points in time, then derive the
    four stage measurements from them."""

    def __init__(self, call_id: str, turn: int):
        self.call_id = call_id
        self.turn = turn
        self.metrics = TurnMetrics()
        self._marks: dict[str, float] = {}

    def mark(self, point: str) -> None:
        self._marks[point] = time.perf_counter()

    def set_mark(self, point: str, perf_counter_value: float) -> None:
        """Backfill a mark measured elsewhere (e.g. inside the STT client)."""
        self._marks[point] = perf_counter_value

    def _elapsed_ms(self, start: str) -> float | None:
        t0 = self._marks.get(start)
        return (time.perf_counter() - t0) * 1000 if t0 else None

    def stt_done(self):
        self.metrics.stt_ms = self._elapsed_ms("audio_sent")

    def llm_first_sentence(self):
        self.metrics.llm_ms = self._elapsed_ms("llm_start")

    def tts_first_audio(self):
        self.metrics.tts_ms = self._elapsed_ms("tts_start")

    def first_audio_out(self):
        self.metrics.e2e_ms = self._elapsed_ms("final_transcript")

    def save(self) -> None:
        m = self.metrics
        storage.add_turn_metrics(self.call_id, self.turn,
                                 m.stt_ms, m.llm_ms, m.tts_ms, m.e2e_ms)

