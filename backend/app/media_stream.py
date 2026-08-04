import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import storage
from app.audio import b64_to_bytes, bytes_to_b64
from app.llm.workflows import WORKFLOWS
from app.pipeline import CallPipeline
from app.session import CallSession
from app.twilio_handler import hangup_call, transfer_call

router = APIRouter()
log = logging.getLogger("media_stream")

@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket) -> None:
    await ws.accept()
    stream_sid: str | None = None
    pipeline: CallPipeline | None = None

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            event = msg.get("event")

            if event == "start":
                start = msg["start"]
                stream_sid = start["streamSid"]
                call_sid = start.get("callSid", "")
                call_id = start.get("customParameters", {}).get("call_id", "")
                log.info("stream started: call_id=%s", call_id)

                record = storage.get_call(call_id)
                if record is None:
                    log.error("unknown call_id %r — closing", call_id)
                    await ws.close()
                    return

                session = CallSession(
                    call_id=call_id,
                    workflow=WORKFLOWS[record["workflow_id"]],
                    context=record["context"],
                    tts_provider=record["tts_provider"],
                    voice_id=record["voice_id"],
                    language=record.get("language", "en"),
                )
                storage.update_call(call_id, status="in_progress",
                                    twilio_call_sid=call_sid)

                # The three capabilities the pipeline needs, in its language:
                async def send_audio(chunk: bytes) -> None:
                    await ws.send_text(json.dumps({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": bytes_to_b64(chunk)},
                    }))

                async def clear_audio() -> None:
                    await ws.send_text(json.dumps({
                        "event": "clear", "streamSid": stream_sid,
                    }))

                async def hangup() -> None:
                    hangup_call(call_sid)

                async def transfer() -> None:
                    transfer_call(call_sid)

                pipeline = CallPipeline(session, send_audio, clear_audio, hangup, transfer)

                pipeline.start()
            elif event == "media" and pipeline is not None:
                await pipeline.handle_audio(b64_to_bytes(msg["media"]["payload"]))
            elif event == "stop":
                log.info("stream stopped by Twilio")
                break

    except WebSocketDisconnect:
        log.info("stream disconnected")
    except Exception:
        log.exception("media stream error")
    finally:
        if pipeline is not None:
            await pipeline.shutdown()
    