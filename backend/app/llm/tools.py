import json
import logging

log = logging.getLogger("tools")

TOOLS_SCHEMAS = {
    "lookup_loan_details": {
        "type": "function",
        "function": {
            "name": "lookup_loan_details",
            "description": (
                "Look up the borrower's loan account: outstanding amount, "
                "due date, days overdue."
            ),
            "parameters": {"type": "object", "properties": {},
                           "required": []},
        }
    },
    "log_promise_to_pay": {
        "type": "function",
        "function": {
            "name": "log_promise_to_pay",
            "description": (
                "Record a borrower's commitment to pay. Call this the "
                "moment they agree to any payment amount or date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number",
                               "description": "Amount in ₹ promised"},
                    "pay_by_date": {"type": "string",
                                    "description": "Date promised, e.g. 2026-08-10"},
                    "notes": {"type": "string",
                              "description": "Short note about the commitment"},
                },
                "required": ["amount", "pay_by_date"],
            },
        }
    },
    "escalate_to_human": {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Transfer the call to a human agent immediately. Use when "
                "the caller is angry, distressed, confused, or explicitly "
                "asks for a person."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string",
                               "description": "Why the call is being escalated"},
                },
                "required": ["reason"],
            },
        },
    },
    "end_call": {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": (
                "End the phone call AFTER the workflow goals are done, or "
                "when the caller clearly declines / is the wrong person / "
                "is busy / asks to stop. Never call this after a simple "
                "'yes' or 'okay' confirmation — keep talking. Always say "
                "goodbye BEFORE calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string",
                               "description": (
                                   "e.g. 'completed', 'no_interest', "
                                   "'caller_requested', 'wrong_person', "
                                   "'callback_requested'"
                               )},
                },
                "required": [],
            },
        },
    },
    "lookup_balance": {
        "type": "function",
        "function": {
            "name": "lookup_balance",
            "description": "Look up the customer's account balance.",
            "parameters": {"type": "object", "properties": {},
                           "required": []},
        },
    },
    "lookup_branch": {
        "type": "function",
        "function": {
            "name": "lookup_branch",
            "description": "Find the nearest branch and its working hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string",
                             "description": "Area or city the caller asks about"},
                },
                "required": [],
            },
        },
    },
    "qualify_lead": {
        "type": "function",
        "function": {
            "name": "qualify_lead",
            "description": "Record how interested a sales lead is.",
            "parameters": {
                "type": "object",
                "properties": {
                    "interest_level": {"type": "string",
                                       "enum": ["hot", "warm", "cold", "not_interested"]},
                    "notes": {"type": "string"},
                },
                "required": ["interest_level"],
            },
        },
    },
}


# ── Handlers ──────────────────────────────────────────────────────────────
# Each handler receives the live CallSession
# plus the LLM's arguments, and returns a string the model will read.
def _lookup_loan_details(session) -> str:
    ctx = session.context
    return json.dumps({
        "borrower": ctx.get("borrower_name") or ctx.get("customer_name"),
        "outstanding_amount": ctx.get("loan_amount") or ctx.get("emi_amount"),
        "due_date": ctx.get("due_date"),
        "days_overdue": ctx.get("days_overdue", 0),
        "note": "Demo data — wire this to your loan management system.",
    })

def _log_promise_to_pay(session, amount, pay_by_date, notes="") -> str:
    session.set_outcome(f"promise_to_pay: ₹{amount} by {pay_by_date}")
    return (f"Recorded: borrower promised to pay ₹{amount} by "
            f"{pay_by_date}. Confirm the commitment back to them warmly.")

def _escalate_to_human(session, reason) -> str:
    session.set_outcome(f"escalated: {reason}")
    session.transfer_requested = True
    return ("Human transfer initiated. Tell the caller you are connecting "
            "them to a human specialist right now, and say goodbye.")

# Reasons that are allowed even on the first caller turn (before goals finish).
_EARLY_EXIT_MARKERS = (
    "wrong_number", "wrong_person", "caller_busy", "busy",
    "callback", "caller_requested", "not_available", "no_interest",
    "decline", "refused", "not_interested", "do_not_call",
)

def _end_call(session, reason="completed") -> str:
    reason = (reason or "completed").strip() or "completed"
    reason_key = reason.lower().replace("-", "_").replace(" ", "_")
    early_ok = any(marker in reason_key for marker in _EARLY_EXIT_MARKERS)

    # Block the common failure mode: caller says "yes" → model thanks them
    # and hangs up before any of the workflow goals run.
    if session.turn <= 1 and not session.outcome and not early_ok:
        log.info("end_call rejected as premature (call %s, turn=%s, reason=%s)",
                 session.call_id, session.turn, reason)
        return (
            "Call not ended — it is too early. The caller only confirmed. "
            "Continue with your next workflow goal right now (for example, "
            "state the overdue amount / EMI / product pitch). Only call "
            "end_call after the goals are finished, or if the caller clearly "
            "asks to stop / is the wrong person / is busy."
        )

    log.info("end_call tool invoked (call %s, reason=%s)",
             session.call_id, reason)
    session.end_requested = True          # the pipeline watches this flag
    if not session.outcome:
        session.set_outcome(reason)
    return "Ending the call now."

def _lookup_balance(session) -> str:
    return json.dumps({
        "account_type": session.context.get("account_type", "Savings"),
        "available_balance": "₹12,450.00",
        "note": "Demo data — wire this to your core banking system.",
    })

def _lookup_branch(session, area="") -> str:
    where = f" in {area}" if area else ""
    return (f"The nearest branch{where} is VoiceFlow Bank, MG Road branch, "
            "open Monday to Saturday, 10 AM to 4 PM.")

def _qualify_lead(session, interest_level, notes="") -> str:
    session.set_outcome(f"lead_{interest_level}")
    return f"Lead recorded as {interest_level}."

HANDLERS = {
    "lookup_loan_details": _lookup_loan_details,
    "log_promise_to_pay": _log_promise_to_pay,
    "escalate_to_human": _escalate_to_human,
    "end_call": _end_call,
    "lookup_balance": _lookup_balance,
    "lookup_branch": _lookup_branch,
    "qualify_lead": _qualify_lead,
}



def execute_tool(session, name: str, arguments: dict) -> str:
    handler = HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    try:
        return handler(session, **arguments)
    except TypeError as exc:
        return f"Tool argument error: {exc}"
