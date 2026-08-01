"""Mock-Backend fuer die MCP-Tools: deterministische Fixture-Daten + Call-Log.

Das Call-Log ist die Ground Truth fuer die deterministischen Checks
(richtiges Tool, richtige Argumente).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    agent: str
    tool: str
    args: dict
    result: str
    t: float = field(default_factory=time.time)


def _ok(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _customer(state: dict, args: dict):
    cid = str(args.get("customer_id", "")).strip().upper()
    return cid, state.get("customers", {}).get(cid)


def h_get_customer(state: dict, args: dict) -> str:
    cid, cust = _customer(state, args)
    if not cust:
        return _err(f"Kunde {cid or '?'} nicht gefunden.")
    return _ok({k: cust[k] for k in ("customer_id", "name", "address", "tariff")})


def h_get_invoices(state: dict, args: dict) -> str:
    cid, cust = _customer(state, args)
    if not cust:
        return _err(f"Kunde {cid or '?'} nicht gefunden.")
    return _ok(cust["invoices"])


def h_create_complaint(state: dict, args: dict) -> str:
    cid, cust = _customer(state, args)
    if not cust:
        return _err(f"Kunde {cid or '?'} nicht gefunden.")
    invoice_id = str(args.get("invoice_id", "")).strip().upper()
    if not any(inv["id"] == invoice_id for inv in cust["invoices"]):
        return _err(f"Rechnung {invoice_id or '?'} existiert fuer Kunde {cid} nicht.")
    complaints = state.setdefault("complaints", [])
    ticket = f"REKLA-{len(complaints) + 1:04d}"
    complaints.append({"ticket": ticket, "customer_id": cid, "invoice_id": invoice_id,
                       "reason": args.get("reason", "")})
    return _ok({"status": "angelegt", "ticket": ticket})


def h_update_address(state: dict, args: dict) -> str:
    cid, cust = _customer(state, args)
    if not cust:
        return _err(f"Kunde {cid or '?'} nicht gefunden.")
    missing = [k for k in ("street", "postal_code", "city") if not str(args.get(k, "")).strip()]
    if missing:
        return _err(f"Fehlende Angaben: {', '.join(missing)}")
    cust["address"] = {k: str(args[k]).strip() for k in ("street", "postal_code", "city")}
    return _ok({"status": "geaendert", "address": cust["address"]})


def h_get_tariffs(state: dict, args: dict) -> str:
    return _ok(state.get("tariffs", []))


def h_escalate_to_human(state: dict, args: dict) -> str:
    escalations = state.setdefault("escalations", [])
    ticket = f"ESK-{len(escalations) + 1:04d}"
    escalations.append({"ticket": ticket, "reason": args.get("reason", "")})
    return _ok({"status": "an Mitarbeiter uebergeben", "ticket": ticket,
                "callback": "Rueckruf innerhalb von 24 Stunden"})


HANDLERS = {
    "get_customer": h_get_customer,
    "get_invoices": h_get_invoices,
    "create_complaint": h_create_complaint,
    "update_address": h_update_address,
    "get_tariffs": h_get_tariffs,
    "escalate_to_human": h_escalate_to_human,
}


class MockToolRuntime:
    def __init__(self, fixtures: dict):
        self.state = fixtures
        self.calls: list[ToolCall] = []

    def execute(self, agent: str, tool: str, args: dict) -> str:
        handler = HANDLERS.get(tool)
        result = handler(self.state, args) if handler else _err(f"Unbekanntes Tool: {tool}")
        self.calls.append(ToolCall(agent=agent, tool=tool, args=args, result=result))
        return result
