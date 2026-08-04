import base64

def b64_to_bytes(payload: str) -> bytes:
    """Twilio -> us: decode a base64 media payload into raw mulaw bytes."""
    return base64.b64decode(payload)

def bytes_to_b64(data: bytes) -> str:
    """Us -> Twilio: encode raw mulaw bytes for a JSON media frame."""
    return base64.b64encode(data).decode("ascii")