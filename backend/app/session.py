import json
from collections import defaultdict

from app import storage
from app.llm.workflows import LANGUAGE_INSTRUCTIONS, WorkflowConfig

class CallSession:
    def __init__(self, call_id: str, workflow: WorkflowConfig,
                 context: dict, tts_provider: str, voice_id: str,
                 language: str = "en"):
        self.call_id = call_id
        self.workflow = workflow
        self.context = context
        self.tts_provider = tts_provider
        self.voice_id = voice_id
        self.language = language
        prompt = self._render(workflow.system_prompt)
        prompt += "\n\n" + LANGUAGE_INSTRUCTIONS.get(
            language, LANGUAGE_INSTRUCTIONS["en"])
        self.messages: list[dict] = [{"role": "system", "content": prompt}]
        self.outcome: str | None = None
        self.capture: dict | None = None
        self.end_requested = False
        self.transfer_requested = False
        self.turn = 0

    @property
    def deepgram_language(self) -> str:
        """Deepgram has no 'hinglish' code — Hinglish audio goes to 'hi'."""
        return "en" if self.language == "en" else "hi"

    def _render(self, template: str) -> str:
        return template.format_map(defaultdict(str, self.context))

    def opening_line(self) -> str:
        return self._render(self.workflow.opening_line)

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        storage.add_transcript(self.call_id, "caller", text)

    def add_assistant_message(self, text: str) -> None:
        if text.strip():
            self.messages.append({"role": "assistant", "content": text})
            storage.add_transcript(self.call_id, "agent", text)

    def set_capture(self, kind: str, summary: str, **fields) -> None:
        """Structured tool result for the call-detail dashboard."""
        self.outcome = summary
        self.capture = {"type": kind, **fields}
        storage.update_call(
            self.call_id,
            outcome=summary,
            capture_json=json.dumps(self.capture),
        )