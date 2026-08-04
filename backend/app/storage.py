import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import settings

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row # rows behave like dicts
    return conn

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_db() -> None:
    """Create tables if they don't exist. Called once at app startup."""
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id              TEXT PRIMARY KEY,
                workflow_id     TEXT NOT NULL,
                phone_number    TEXT NOT NULL,
                tts_provider    TEXT NOT NULL,
                voice_id        TEXT NOT NULL,
                voice_name      TEXT NOT NULL DEFAULT '',
                context_json    TEXT NOT NULL DEFAULT '{}',
                language        TEXT NOT NULL DEFAULT 'en',
                status          TEXT NOT NULL DEFAULT 'initiated',
                outcome         TEXT,
                twilio_call_sid TEXT,
                started_at      TEXT NOT NULL,
                ended_at        TEXT,
                duration_sec    REAL
            );
            CREATE TABLE IF NOT EXISTS transcripts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL,
                role    TEXT NOT NULL,       -- 'agent' or 'caller'
                text    TEXT NOT NULL,
                ts      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turn_metrics (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL,
                turn    INTEGER NOT NULL,
                stt_ms  REAL,
                llm_ms  REAL,
                tts_ms  REAL,
                e2e_ms  REAL
            );
            """
        )

def create_call(workflow_id, phone_number, tts_provider, voice_id,
                voice_name, context, language="en") -> str:
    """Insert a new call row (status 'initiated') and return its id."""
    call_id = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO calls (id, workflow_id, phone_number, tts_provider,"
            " voice_id, voice_name, context_json, status, started_at, language)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (call_id, workflow_id, phone_number, tts_provider, voice_id,
             voice_name, json.dumps(context), "initiated", _now(), language),
        )
    return call_id

def update_call(call_id: str, **fields) -> None:
    """Update arbitrary columns on a call: update_call(id, status='failed')."""
    if not fields:
        return
    cols = ", ".join(f"{field} = ?" for field in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE calls SET {cols} WHERE id = ?",
                     (*fields.values(), call_id))

def end_call_record(call_id: str, status: str = "completed") -> None:
    """Stamp the end time and compute duration from started_at."""
    with _conn() as conn:
        row = conn.execute("SELECT started_at FROM calls WHERE id = ?",
                           (call_id,)).fetchone()

        duration = None

        if row:
            started = datetime.fromisoformat(row["started_at"])
            duration = (datetime.now(timezone.utc) - started).total_seconds()

        conn.execute(
            "UPDATE calls SET status = ?, ended_at = ?, duration_sec = ?"
            " WHERE id = ?",
            (status, _now(), duration, call_id),
        )

def add_transcript(call_id: str, role: str, text: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO transcripts (call_id, role, text, ts)"
            " VALUES (?,?,?,?)",
            (call_id, role, text, _now())
        )

def add_turn_metrics(call_id, turn, stt_ms, llm_ms, tts_ms, e2e_ms) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO turn_metrics (call_id, turn, stt_ms, llm_ms,"
            " tts_ms, e2e_ms) VALUES (?,?,?,?,?,?)",
             (call_id, turn, stt_ms, llm_ms, tts_ms, e2e_ms),                        
        )

def _row_to_call(row) -> dict:
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "phone_number": row["phone_number"],
        "tts_provider": row["tts_provider"],
        "voice_id": row["voice_id"],
        "voice_name": row["voice_name"],
        "context": json.loads(row["context_json"]),
        "language": row["language"],
        "status": row["status"],
        "outcome": row["outcome"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_sec": row["duration_sec"],
    }


def list_calls() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM calls ORDER BY started_at DESC LIMIT 50"
        ).fetchall()
    return [_row_to_call(row) for row in rows]

def _percentile(values: list[float], pct: int):
    """Nearest-rank percentile — good enough for a demo dashboard."""
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round((pct / 100) * (len(values) - 1))))
    return values[k]

def get_call(call_id: str):
    """One call with its transcript and aggregated latency metrics."""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id = ?",
                           (call_id,)).fetchone()

        if not row:
            return None
        transcript = [
            dict(transcript_row) for transcript_row in conn.execute(
                "SELECT role, text, ts AS timestamp FROM transcripts"
                " WHERE call_id = ? ORDER BY id", (call_id,)
            ).fetchall()
        ]

        turns = conn.execute(
            "SELECT stt_ms, llm_ms, tts_ms, e2e_ms FROM turn_metrics"
            " WHERE call_id = ?", (call_id,)
        ).fetchall()

    call = _row_to_call(row)
    call["transcript"] = transcript

    if turns:
        def avg(key):
            vals = [turn[key] for turn in turns if turn[key] is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        e2e_vals = [turn["e2e_ms"] for turn in turns if turn["e2e_ms"] is not None]
        p95 = _percentile(e2e_vals, 95)
        call["metrics"] = {
            "turns": len(turns),
            "stt_avg_ms": avg("stt_ms"),
            "llm_avg_ms": avg("llm_ms"),
            "tts_avg_ms": avg("tts_ms"),
            "e2e_avg_ms": avg("e2e_ms"),
            "e2e_p95_ms": round(p95, 1) if p95 is not None else None,
        }
    else:
        call["metrics"] = None

    return call

