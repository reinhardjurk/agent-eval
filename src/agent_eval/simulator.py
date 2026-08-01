"""LLM-basierter User-Simulator: spielt den Kunden gemaess Szenario-Persona."""

from __future__ import annotations

from .config import Scenario
from .llm import extract_text
from .tracing import Tracer

DONE_MARKER = "[DONE]"

SYSTEM_TEMPLATE = """Du simulierst eine Person in einem Sprachdialog mit einem Assistenten.

Setting: {setting}

Persona: {persona}

Dein Anliegen (Ziel): {goal}

Verhalten: {constraints}

Regeln:
- Antworte ausschliesslich mit deiner naechsten gesprochenen Aeusserung als Kunde. Kurz und natuerlich, wie am Telefon.
- Bleibe konsequent in der Rolle. Du bist der Kunde, nicht der Assistent.
- Gib Informationen (z.B. Kundennummer) nur preis, wie es dein Verhalten vorgibt.
- Wenn dein Anliegen vollstaendig erledigt ist ODER du entnervt aufgibst, beginne deine Antwort exakt mit {done} gefolgt von einem kurzen Abschlusssatz.
- Beende das Gespraech nicht vorschnell: erst wenn du eine konkrete Bestaetigung (z.B. Ticketnummer oder Zusage) erhalten hast oder klar ist, dass dir nicht geholfen wird."""


class UserSimulator:
    def __init__(self, llm, scenario: Scenario, tracer: Tracer):
        self.llm = llm
        self.tracer = tracer
        self.system = SYSTEM_TEMPLATE.format(
            setting=scenario.setting,
            persona=scenario.persona,
            goal=scenario.goal,
            constraints=scenario.constraints or "unauffaellig, kooperativ",
            done=DONE_MARKER,
        )

    def next_message(self, transcript: list[dict]) -> tuple[str, bool]:
        convo = "\n".join(
            f"{'Kunde' if m['role'] == 'customer' else 'Assistent'}: {m['text']}"
            for m in transcript
        )
        prompt = f"Bisheriges Gespraech:\n{convo}\n\nWas sagst du als Kunde als Naechstes?"
        text = ""
        for _ in range(2):  # ein Retry bei leerer Antwort (lokale Modelle)
            with self.tracer.generation("user-simulator", self.llm.model, input=prompt) as gen:
                res = self.llm.complete(self.system, [{"role": "user", "content": prompt}])
                text = extract_text(res.message).strip()
                gen.record(res, output=text)
            if text:
                break
        if text.startswith(DONE_MARKER):
            return text[len(DONE_MARKER):].strip(" :,-"), True
        return text, False
