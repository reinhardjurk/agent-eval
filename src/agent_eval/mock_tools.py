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


# ------------------------------------------------- Automotive (Fahrzeug-Domaene)


def h_start_navigation(state: dict, args: dict) -> str:
    destination = str(args.get("destination", "")).strip()
    if not destination:
        return _err("Kein Ziel angegeben.")
    # deterministische Pseudo-Route aus dem Zielnamen
    seed = sum(ord(c) for c in destination)
    distance_km = 5 + seed % 320
    route = {"ziel": destination, "distanz_km": distance_km,
             "ankunft_in_min": int(distance_km * 0.9)}
    state.setdefault("vehicle", {})["active_route"] = route
    return _ok({"status": "Route gestartet", **route})


def h_find_poi(state: dict, args: dict) -> str:
    category = str(args.get("category", "")).strip().lower()
    pois = state.get("pois", {})
    for key, entries in pois.items():
        if key in category or category in key:
            return _ok(entries)
    return _err(f"Unbekannte Kategorie '{category}'. Verfuegbar: {', '.join(pois)}")


def h_add_stopover(state: dict, args: dict) -> str:
    route = state.get("vehicle", {}).get("active_route")
    if not route:
        return _err("Keine aktive Route. Bitte zuerst eine Navigation starten.")
    name = str(args.get("name", "")).strip()
    if not name:
        return _err("Kein Zwischenziel angegeben.")
    route.setdefault("zwischenstopps", []).append(name)
    route["ankunft_in_min"] += 15
    return _ok({"status": "Zwischenstopp eingeplant", "zwischenstopp": name,
                "neue_ankunft_in_min": route["ankunft_in_min"]})


def h_get_traffic_info(state: dict, args: dict) -> str:
    route = state.get("vehicle", {}).get("active_route")
    if route:
        return _ok({"route": route["ziel"],
                    "stoerungen": [{"art": "stockender Verkehr", "laenge_km": 4,
                                    "verzoegerung_min": 12}],
                    "empfehlung": "Auf der Route bleiben, eine Umfahrung spart keine Zeit."})
    return _ok({"stoerungen": [{"art": "Unfall auf der A7 Richtung Norden",
                                "verzoegerung_min": 25}],
                "hinweis": "Keine aktive Route – Angaben gelten fuer das Umfeld."})


def h_play_media(state: dict, args: dict) -> str:
    query = str(args.get("query", "")).strip().lower()
    if not query:
        return _err("Keine Suchanfrage angegeben.")
    for item in state.get("media", []):
        haystack = f"{item['titel']} {item['interpret']}".lower()
        if any(token in haystack for token in query.split()):
            state.setdefault("vehicle", {})["now_playing"] = item
            return _ok({"status": "Wiedergabe gestartet", **item})
    return _err(f"Zu '{query}' wurde in der Mediathek nichts gefunden. "
                "Alternativ steht Radio zur Verfuegung.")


def h_set_volume(state: dict, args: dict) -> str:
    try:
        level = int(args.get("level"))
    except (TypeError, ValueError):
        return _err("Lautstaerke muss eine Zahl von 0 bis 10 sein.")
    if not 0 <= level <= 10:
        return _err("Lautstaerke muss zwischen 0 und 10 liegen.")
    state.setdefault("vehicle", {})["volume"] = level
    return _ok({"status": "Lautstaerke gesetzt", "level": level})


def h_tune_radio(state: dict, args: dict) -> str:
    station = str(args.get("station", "")).strip().lower()
    if not station:
        return _err("Kein Sender angegeben.")
    for entry in state.get("radio", []):
        if station in entry["sender"].lower() or entry["sender"].lower() in station:
            state.setdefault("vehicle", {})["now_playing"] = entry
            return _ok({"status": "Sender eingestellt", **entry})
    available = ", ".join(e["sender"] for e in state.get("radio", []))
    return _err(f"Sender '{station}' nicht gefunden. Verfuegbar: {available}")


def h_set_temperature(state: dict, args: dict) -> str:
    zone = str(args.get("zone", "alle")).strip().lower()
    try:
        celsius = float(args.get("celsius"))
    except (TypeError, ValueError):
        return _err("Temperatur muss eine Zahl sein.")
    if not 16 <= celsius <= 28:
        return _err("Temperatur muss zwischen 16 und 28 Grad liegen.")
    climate = state.setdefault("vehicle", {}).setdefault(
        "climate", {"fahrer": 20.0, "beifahrer": 20.0, "hinten": 20.0})
    if zone == "alle":
        for key in climate:
            climate[key] = celsius
    elif zone in climate:
        climate[zone] = celsius
    else:
        return _err(f"Unbekannte Zone '{zone}'. Verfuegbar: alle, {', '.join(climate)}")
    return _ok({"status": "Temperatur gesetzt", "zone": zone, "celsius": celsius})


def h_set_seat_heating(state: dict, args: dict) -> str:
    seat = str(args.get("seat", "fahrer")).strip().lower()
    if seat not in ("fahrer", "beifahrer"):
        return _err("Unbekannter Sitz. Verfuegbar: fahrer, beifahrer")
    try:
        level = int(args.get("level"))
    except (TypeError, ValueError):
        return _err("Stufe muss eine Zahl von 0 bis 3 sein.")
    if not 0 <= level <= 3:
        return _err("Stufe muss zwischen 0 und 3 liegen.")
    state.setdefault("vehicle", {}).setdefault("seat_heating", {})[seat] = level
    return _ok({"status": "Sitzheizung gesetzt", "seat": seat, "level": level})


def h_activate_defrost(state: dict, args: dict) -> str:
    state.setdefault("vehicle", {})["defrost"] = True
    return _ok({"status": "Scheibenenteisung aktiviert",
                "hinweis": "Frontscheibe ist in etwa zwei Minuten frei."})


HANDLERS = {
    # Telco/CRM
    "get_customer": h_get_customer,
    "get_invoices": h_get_invoices,
    "create_complaint": h_create_complaint,
    "update_address": h_update_address,
    "get_tariffs": h_get_tariffs,
    "escalate_to_human": h_escalate_to_human,
    # Automotive
    "start_navigation": h_start_navigation,
    "find_poi": h_find_poi,
    "add_stopover": h_add_stopover,
    "get_traffic_info": h_get_traffic_info,
    "play_media": h_play_media,
    "set_volume": h_set_volume,
    "tune_radio": h_tune_radio,
    "set_temperature": h_set_temperature,
    "set_seat_heating": h_set_seat_heating,
    "activate_defrost": h_activate_defrost,
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
