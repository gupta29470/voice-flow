import logging

from fastapi import APIRouter, Response
from twilio.rest import Client

from app.config import settings

router = APIRouter()
log = logging.getLogger("twilio")

def _client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)

def place_call(call_id: str, to_number: str) -> str:
    """Ask Twilio to dial `to_number`. When answered, Twilio fetches TwiML
    from the `url` below. Returns the Twilio Call SID."""
    call = _client().calls.create(
        to=to_number,
        from_=settings.twilio_phone_number,
        # NOTE: no method= param — Twilio TRIAL accounts reject it with
        # HTTP 400 "trial accounts have limited parameter access".
        # The url webhook defaults to POST, so nothing is lost.
        url=f"{settings.public_url}/twilio/voice?call_id={call_id}",
    )

    return call.sid

def transfer_call(call_sid: str) -> None:
    """Redirect the live call to the human handoff number (cold transfer)."""
    if not settings.human_handoff_number:
        log.error("HUMAN_HANDOFF_NUMBER not set — cannot transfer")
        return
    twiml = f"<Response><Dial>{settings.human_handoff_number}</Dial></Response>"
    try:
        _client().calls(call_sid).update(twiml=twiml)
    except Exception:
        log.exception("transfer failed for %s", call_sid)
        

def hangup_call(call_sid: str) -> None:
    """End a live call — used after the agent says its goodbye."""
    try:
        _client().calls(call_sid).update(status="completed")
    except Exception:
        log.exception("hangup failed for %s", call_sid)

@router.post("/twilio/voice")
async def voice_webhook(call_id: str = "") -> Response:
    """Answered call → tell Twilio to open a media stream back to us,
    carrying our call_id so the gateway can look up the session."""
    ws_url = (settings.public_url
              .replace("https://", "wss://")
              .replace("http://", "ws://"))
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}/twilio/stream">
      <Parameter name="call_id" value="{call_id}" />
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")