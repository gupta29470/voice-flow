import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import storage
from app.config import settings
from app.llm.workflows import SUPPORTED_LANGUAGES, WORKFLOWS
from app.media_stream import router as media_router
from app.tts.base import get_provider
from app.twilio_handler import place_call, router as twilio_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    yield

app = FastAPI(title="VoiceFlow", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(twilio_router)    # /twilio/voice
app.include_router(media_router)     # /twilio/stream (WebSocket)


class StartCallRequest(BaseModel):
    workflow_id: str
    phone_number: str
    tts_provider: str
    voice_id: str
    voice_name: str = ""
    language: str = "en"
    context: dict[str, str] = {}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/workflows")
def list_workflows():
    """The dashboard builds its whole form from this response."""
    return {"workflows": [
        {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "fields": [vars(field) for field in workflow.fields],
        }

        for workflow in WORKFLOWS.values()
    ]}

# provider name -> (fetched_at_epoch, [Voice, ...])
_voice_cache: dict[str, tuple[float, list]] = {}
_VOICE_CACHE_TTL = 300   # seconds

@app.get("/api/voices")
async def list_voices():
    voices = []
    for name in ("cartesia", "elevenlabs"):
        try:
            cached = _voice_cache.get(name)
            if cached and time.time() - cached[0] < _VOICE_CACHE_TTL:
                voices.extend(cached[1])
                continue
            provider = get_provider(name)
            fresh = await provider.list_voices()
            _voice_cache[name] = (time.time(), fresh)
            voices.extend(fresh)
        except Exception:
            log.exception("voice list failed for %s", name)
    return {"voices": [vars(v) for v in voices]}

def _voicename(provider_name: str, voice_id: str) -> str:
    cached = _voice_cache.get(provider_name)
    if cached:
        for voice in cached[1]:
            if voice.id == voice_id:
                return voice.name
    return voice_id


@app.post("/api/calls", status_code=201)
async def start_call(request: StartCallRequest):
    if request.workflow_id not in WORKFLOWS:
        raise HTTPException(404, f"Unknown workflow: {request.workflow_id}")
    if request.tts_provider not in ("cartesia", "elevenlabs"):
        raise HTTPException(400, f"Unknown TTS provider: {request.tts_provider}")
    if request.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Unknown language: {request.language}")

    call_id = storage.create_call(
        workflow_id=request.workflow_id,
        phone_number=request.phone_number,
        tts_provider=request.tts_provider,
        voice_id=request.voice_id,
        voice_name=request.voice_name or _voicename(request.tts_provider, request.voice_id),
        context=request.context,
        language=request.language,
    )

    try:
        sid = place_call(call_id, request.phone_number)
        storage.update_call(call_id, twilio_call_sid=sid)
    except Exception as exc:
        storage.update_call(call_id, status="failed")
        log.exception("Twilio could not place the call")
        raise HTTPException(502, f"Twilio could not place the call: {exc}")

    return {"call_id": call_id, "status": "initiated"}

@app.get("/api/calls")
def list_calls():
    return {"calls": storage.list_calls()}


@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    call = storage.get_call(call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    return call
    