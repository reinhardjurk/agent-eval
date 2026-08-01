"""Generator fuer Automotive-Kundendialoge (Navigation, Entertainment, Klima).

Erzeugt lauffaehige Szenario-YAMLs fuer die Fahrzeug-Domaene (configs/auto-*.yaml):
jedes Szenario kombiniert einen Dialog-Blueprint (Ziel + Erfolgskriterien gegen
die car-Tools) mit zufaellig gewaehlten Personas, Parametern und Eigenheiten.
Deterministisch per --seed, Menge per --count.

    python -m agent_eval.scenario_gen --count 20 --out scenarios/auto --seed 42
    python -m agent_eval.scenario_gen --count 6 --domains klima,kombi
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import yaml

from .config import Scenario

SETTING = ("Du sitzt im Auto (als Fahrer oder Beifahrer) und sprichst per Sprachsteuerung "
           "mit 'Nova', dem Sprachassistenten des Fahrzeugs.")

PERSONAS = [
    "Gestresste Pendlerin, 41, spaet dran zu einem wichtigen Termin; spricht schnell und knapp.",
    "Rentner, 72, faehrt zum ersten Mal ein Elektroauto und misstraut 'dem Computer'; will alles bestaetigt haben.",
    "Vertriebler, 29, zwischen zwei Kundenterminen; Zeit ist Geld, Hoeflichkeitsfloskeln nerven ihn.",
    "Studentin, 22, auf der Nachtfahrt zurueck vom Festival; muede, will es vor allem gemuetlich.",
    "Aufgeregter Fahranfaenger, 18, auf seiner ersten langen Autobahnfahrt allein.",
    "Resolute Grossmutter, 68, auf dem Beifahrersitz; der Fahrer soll sich aufs Fahren konzentrieren, also uebernimmt sie das Reden.",
    "Musikliebhaber, 34, Vinyl-Nostalgiker; benutzt altmodische Begriffe wie 'Sender' und 'Kassette'.",
    "Perfektionistin, 45, will exakte Werte und laesst sich nichts aufrunden.",
    "Gut gelaunter Taxifahrer, 51, plaudert gern, kommt aber immer wieder zum Anliegen zurueck.",
]

TWISTS = [
    "Wird ungeduldig, wenn der Assistent mehr als einen Satz am Stueck redet.",
    "Formuliert das Anliegen zunaechst indirekt und wird erst auf Nachfrage konkret.",
    "Stellt zwischendurch eine kurze, irrelevante Gegenfrage, kehrt dann zum Anliegen zurueck.",
    "Nuschelt Zahlen und Namen; wiederholt sie deutlich, wenn der Assistent nachfragt.",
    "Aendert mitten im Gespraech einmal kurz die Meinung, kehrt dann zum urspruenglichen Wunsch zurueck.",
]

NAV_DESTINATIONS = [
    ("Luebeck", "zur Taufe deiner Enkelin"),
    ("Heidelberg", "zu einem Klassentreffen nach zwanzig Jahren"),
    ("Muenchen", "zu einem Bewerbungsgespraech, bei dem du puenktlich sein musst"),
    ("Freiburg", "zu einem Weinfest mit alten Freunden"),
    ("Leipzig", "zu einem Konzert, das um acht beginnt"),
    ("Bremerhaven", "mit den Kindern ins Klimahaus"),
]

MEDIA_WISHES = [
    ("den Song 'Bohemian Rhapsody' von Queen", "*bohemian*"),
    ("'Atemlos durch die Nacht' von Helene Fischer", "*atemlos*"),
    ("die Playlist 'Late Night Jazz'", "*jazz*"),
    ("die neueste Folge des True-Crime-Podcasts 'Kaltblut'", "*kaltblut*"),
]

RADIO_WISHES = [
    ("Antenne Nord", "*antenne*"),
    ("Klassik Plus", "*klassik*"),
    ("Info 24, wegen der Nachrichten", "*info*"),
]


# ------------------------------------------------------------------ Blueprints
# Jeder Blueprint liefert ein Szenario-Grundgeruest; persona=None wird spaeter
# aus dem Pool gefuellt, feste Personas (z.B. Familie) bleiben stehen.

def bp_nav_ziel(rng: random.Random) -> dict:
    city, occasion = rng.choice(NAV_DESTINATIONS)
    return {
        "slug": "nav-ziel",
        "persona": None,
        "goal": f"Du willst nach {city} fahren, {occasion}. Die Navigation soll gestartet "
                f"werden und du willst die Ankunftszeit wissen.",
        "constraints": "",
        "opening": rng.choice([
            f"Fahr mich nach {city}.",
            f"Ich muss nach {city}. Wie lange brauchen wir?",
            f"Navigation nach {city}, bitte.",
        ]),
        "max_turns": 6,
        "criteria": {
            "tool_calls": [{"tool": "start_navigation",
                            "with_args": {"destination": f"*{city.lower()}*"}}],
        },
    }


def bp_nav_laden(rng: random.Random) -> dict:
    percent = rng.choice([9, 12, 15])
    return {
        "slug": "nav-laden",
        "persona": "Leicht nervoeser E-Auto-Neuling, 39, mit Reichweitenangst.",
        "goal": f"Der Akku ist bei {percent} Prozent. Du willst die naechste Ladestation "
                f"finden und wissen, wie weit sie weg ist und ob dort etwas frei ist.",
        "constraints": "Du wirst zunehmend nervoes, je laenger es dauert.",
        "opening": rng.choice([
            "Oh oh, der Akku wird eng. Wo kann ich hier schnell laden?",
            f"Ich hab nur noch {percent} Prozent! Such mir sofort eine Ladesaeule.",
        ]),
        "max_turns": 6,
        "criteria": {
            "tool_calls": [{"tool": "find_poi", "with_args": {"category": "*lade*"}}],
        },
    }


def bp_nav_stopp(rng: random.Random) -> dict:
    city, occasion = rng.choice(NAV_DESTINATIONS)
    return {
        "slug": "nav-stopp",
        "persona": None,
        "goal": f"Du faehrst nach {city}, {occasion}. Unterwegs willst du an einem Restaurant "
                f"halten. Die Navigation soll gestartet und der Zwischenstopp fest eingeplant werden.",
        "constraints": "Du nennst erst das Ziel und kommst erst danach mit dem Essenswunsch.",
        "opening": f"Wir muessen nach {city}, und irgendwann brauch ich unterwegs was zu essen.",
        "max_turns": 8,
        "criteria": {
            "tool_calls": [
                {"tool": "start_navigation", "with_args": {"destination": f"*{city.lower()}*"}},
                {"tool": "add_stopover"},
            ],
        },
    }


def bp_nav_stau(rng: random.Random) -> dict:
    return {
        "slug": "nav-stau",
        "persona": None,
        "goal": "Du hast im Radio von einem Unfall auf der A7 gehoert und willst nur wissen, "
                "wie die Verkehrslage aussieht und ob du betroffen bist. Du willst KEINE neue "
                "Route starten, nur die Auskunft.",
        "constraints": "Wenn der Assistent ungefragt eine neue Navigation starten will, lehnst du ab.",
        "opening": "Sag mal, auf der A sieben soll ein Unfall sein. Sieht's bei uns schlimm aus?",
        "max_turns": 5,
        "criteria": {
            "tool_calls": [{"tool": "get_traffic_info"}],
            "forbidden_tools": ["start_navigation"],
        },
    }


def bp_ent_musik(rng: random.Random) -> dict:
    wish, pattern = rng.choice(MEDIA_WISHES)
    return {
        "slug": "ent-musik",
        "persona": None,
        "goal": f"Du willst {wish} hoeren und eine Bestaetigung, dass es jetzt laeuft.",
        "constraints": "",
        "opening": rng.choice([
            "Mach mal Musik an, ich sag dir gleich was.",
            "Ich brauch was auf die Ohren.",
        ]),
        "max_turns": 6,
        "criteria": {
            "tool_calls": [{"tool": "play_media", "with_args": {"query": pattern}}],
        },
    }


def bp_ent_radio(rng: random.Random) -> dict:
    wish, pattern = rng.choice(RADIO_WISHES)
    return {
        "slug": "ent-radio",
        "persona": None,
        "goal": f"Du willst den Radiosender {wish} hoeren.",
        "constraints": "",
        "opening": "Schalt mal das Radio ein.",
        "max_turns": 5,
        "criteria": {
            "tool_calls": [{"tool": "tune_radio", "with_args": {"station": pattern}}],
        },
    }


def bp_ent_kinder(rng: random.Random) -> dict:
    return {
        "slug": "ent-kinder",
        "persona": "Familienvater, 38, auf Urlaubsfahrt; zwei quengelnde Kinder (6 und 9) "
                   "im Fond mischen sich lautstark ins Gespraech ein.",
        "goal": "Die Kinder wollen ihre Kinderlieder hoeren. Du willst, dass die "
                "Kinderlieder-Playlist laeuft, damit endlich Ruhe ist.",
        "constraints": "Die Kinder rufen dazwischen ('LAUTER!', 'Nicht das!'); du bleibst beim Wunsch nach Kinderliedern.",
        "opening": "Okay okay! Nova, mach den Kindern ihre Lieder an, sonst dreh ich durch.",
        "max_turns": 6,
        "criteria": {
            "tool_calls": [{"tool": "play_media", "with_args": {"query": "*kinderlieder*"}}],
        },
    }


def bp_ent_leiser(rng: random.Random) -> dict:
    return {
        "slug": "ent-leiser",
        "persona": None,
        "goal": "Du bekommst gleich einen wichtigen Anruf. Die Musik soll auf Stufe zwei "
                "runtergeregelt werden. Neue Musik willst du ausdruecklich nicht.",
        "constraints": "",
        "opening": "Mach die Musik leiser, so auf Stufe zwei, ich krieg gleich einen Anruf.",
        "max_turns": 4,
        "criteria": {
            "tool_calls": [{"tool": "set_volume", "with_args": {"level": "2"}}],
            "forbidden_tools": ["play_media"],
        },
    }


def bp_klima_frieren(rng: random.Random) -> dict:
    degrees = rng.choice([22, 23, 24])
    return {
        "slug": "klima-frieren",
        "persona": None,
        "goal": f"Dir ist kalt. Du willst, dass es waermer wird, {degrees} Grad waeren gut. "
                f"Du sagst die Zahl aber erst, wenn der Assistent nachfragt oder von sich aus "
                f"einen Wert vorschlaegt.",
        "constraints": "Du beschreibst das Anliegen zuerst indirekt ('mir ist kalt'), nicht als Befehl.",
        "opening": "Brr. Ist das nur mir so, oder ist es hier drin eiskalt?",
        "max_turns": 5,
        "criteria": {
            "tool_calls": [{"tool": "set_temperature", "with_args": {"celsius": f"{degrees}*"}}],
        },
    }


def bp_klima_scheibe(rng: random.Random) -> dict:
    return {
        "slug": "klima-scheibe",
        "persona": None,
        "goal": "Die Frontscheibe ist ploetzlich komplett beschlagen, du siehst kaum noch etwas. "
                "Die Scheibe soll SOFORT enteist werden, ohne Diskussion.",
        "constraints": "Du bist in einer akuten Stresssituation und wirst laut, wenn Rueckfragen kommen.",
        "opening": "Ich seh nichts mehr! Die Scheibe ist total beschlagen, mach was!",
        "max_turns": 4,
        "criteria": {
            "tool_calls": [{"tool": "activate_defrost"}],
        },
    }


def bp_klima_streit(rng: random.Random) -> dict:
    return {
        "slug": "klima-streit",
        "persona": "Ehepaar auf Langstrecke: Er (faehrt) schwitzt schnell, ihr ist immer kalt. "
                   "Beide reden abwechselnd mit dem Assistenten, leicht gereizt, aber liebevoll.",
        "goal": "Ihr wollt getrennte Temperaturen: Fahrerseite 20 Grad, Beifahrerseite 24 Grad. "
                "Erst wenn beide Zonen eingestellt sind, seid ihr zufrieden.",
        "constraints": "Ihr sprecht durcheinander: erst nennt er seinen Wunsch, dann sie ihren.",
        "opening": "Nova, wir haben hier ein Klimaproblem in der Ehe. Ich will's kuehler, sie will's waermer.",
        "max_turns": 7,
        "criteria": {
            "tool_calls": [
                {"tool": "set_temperature", "with_args": {"zone": "*fahrer*", "celsius": "20*"}},
                {"tool": "set_temperature", "with_args": {"zone": "*beifahrer*", "celsius": "24*"}},
            ],
        },
    }


def bp_klima_sitz(rng: random.Random) -> dict:
    return {
        "slug": "klima-sitz",
        "persona": "Handwerker, 48, nach einem langen Arbeitstag mit Ruecken; brummig, aber herzlich.",
        "goal": "Dein Ruecken macht Probleme. Du willst die Sitzheizung auf dem Fahrersitz "
                "auf die hoechste Stufe (drei).",
        "constraints": "",
        "opening": "Mein Ruecken bringt mich um. Mach mal den Sitz warm, volle Pulle.",
        "max_turns": 4,
        "criteria": {
            "tool_calls": [{"tool": "set_seat_heating",
                            "with_args": {"seat": "*fahrer*", "level": "3"}}],
        },
    }


def bp_klima_hund(rng: random.Random) -> dict:
    return {
        "slug": "klima-hund",
        "persona": "Hundebesitzer, 55, mit hechelndem Golden Retriever auf der Rueckbank; "
                   "der Hund ist ihm wichtiger als er selbst.",
        "goal": "Deinem Hund hinten ist es zu warm, er hechelt stark. Hinten soll es auf "
                "18 Grad abgekuehlt werden; vorne soll alles bleiben, wie es ist.",
        "constraints": "Du redest zwischendurch mit dem Hund ('Gleich wird's besser, Balu').",
        "opening": "Der Balu hechelt hinten wie verrueckt. Kannst du's ihm da kuehler machen?",
        "max_turns": 5,
        "criteria": {
            "tool_calls": [{"tool": "set_temperature",
                            "with_args": {"zone": "*hint*", "celsius": "18*"}}],
        },
    }


def bp_kombi_date(rng: random.Random) -> dict:
    return {
        "slug": "kombi-date",
        "persona": "Nervoeser Mittdreissiger auf dem Weg zum ersten Date seit Jahren; "
                   "redet zu viel, wenn er aufgeregt ist.",
        "goal": "Du willst drei Dinge: Navigation zur 'Trattoria Bella Vista', entspannte Musik "
                "gegen die Nervositaet, und angenehme 22 Grad im Auto. Erst wenn alles drei "
                "erledigt ist, bist du zufrieden.",
        "constraints": "Du nennst die Wuensche nacheinander, nicht alle auf einmal.",
        "opening": "Nova, heute muss alles perfekt sein. Erstmal: bring mich zur Trattoria Bella Vista.",
        "max_turns": 10,
        "criteria": {
            "tool_calls": [
                {"tool": "start_navigation", "with_args": {"destination": "*bella*"}},
                {"tool": "play_media", "with_args": {"query": "*entspann*"}},
                {"tool": "set_temperature", "with_args": {"celsius": "22*"}},
            ],
        },
    }


def bp_kombi_pendler(rng: random.Random) -> dict:
    city, _ = rng.choice(NAV_DESTINATIONS)
    return {
        "slug": "kombi-pendler",
        "persona": "Gestresste Pendlerin, 41, jeden Morgen dieselbe Routine; erwartet, dass "
                   "der Assistent mitdenkt und keine Zeit verschwendet.",
        "goal": f"Morgenroutine: Navigation zur Firmenzentrale in {city} starten und die "
                f"Nachrichten auf Info 24 einschalten.",
        "constraints": "Du gibst beide Wuensche in einem einzigen Satz und erwartest, dass beides passiert.",
        "opening": f"Ab ins Buero nach {city}, und mach die Nachrichten an.",
        "max_turns": 6,
        "criteria": {
            "tool_calls": [
                {"tool": "start_navigation", "with_args": {"destination": f"*{city.lower()}*"}},
                {"tool": "tune_radio", "with_args": {"station": "*info*"}},
            ],
        },
    }


def bp_kombi_urlaub(rng: random.Random) -> dict:
    return {
        "slug": "kombi-urlaub",
        "persona": "Familienvater, 38, Urlaubsstart an die Ostsee; zwei aufgekratzte Kinder "
                   "(6 und 9) im Fond, die Vorfreude ist ohrenbetaeubend.",
        "goal": "Urlaubsfahrt: Navigation zum Timmendorfer Strand starten und fuer die Kinder "
                "die Kinderlieder-Playlist anmachen.",
        "constraints": "Die Kinder rufen dazwischen; du bleibst geduldig und wiederholst notfalls.",
        "opening": "So, Urlaub! Timmendorfer Strand, wir kommen. Und die Kinder wollen ihre Lieder.",
        "max_turns": 8,
        "criteria": {
            "tool_calls": [
                {"tool": "start_navigation", "with_args": {"destination": "*timmendorf*"}},
                {"tool": "play_media", "with_args": {"query": "*kinderlieder*"}},
            ],
        },
    }


BLUEPRINTS: dict[str, list] = {
    "navigation": [bp_nav_ziel, bp_nav_laden, bp_nav_stopp, bp_nav_stau],
    "entertainment": [bp_ent_musik, bp_ent_radio, bp_ent_kinder, bp_ent_leiser],
    "klima": [bp_klima_frieren, bp_klima_scheibe, bp_klima_streit, bp_klima_sitz, bp_klima_hund],
    "kombi": [bp_kombi_date, bp_kombi_pendler, bp_kombi_urlaub],
}


# ------------------------------------------------------------------- Generator


def generate(count: int, domains: list[str], seed: int) -> list[dict]:
    rng = random.Random(seed)
    unknown = [d for d in domains if d not in BLUEPRINTS]
    if unknown:
        raise ValueError(f"Unbekannte Domaene(n): {', '.join(unknown)}. "
                         f"Verfuegbar: {', '.join(BLUEPRINTS)}")

    scenarios: list[dict] = []
    for i in range(count):
        domain = domains[i % len(domains)]           # gleichmaessig ueber Domaenen
        blueprint = rng.choice(BLUEPRINTS[domain])
        draft = blueprint(rng)

        persona = draft["persona"] or rng.choice(PERSONAS)
        constraints = draft["constraints"]
        if rng.random() < 0.6:                       # Eigenheiten zumischen
            twist = rng.choice(TWISTS)
            constraints = f"{constraints} {twist}".strip()

        data = {
            "id": f"{draft['slug']}-{i + 1:02d}",
            "setting": SETTING,
            "persona": persona,
            "goal": draft["goal"],
            "constraints": constraints,
            "opening_message": draft["opening"],
            "max_turns": draft["max_turns"],
            "success_criteria": draft["criteria"],
        }
        Scenario(**data)                             # Schema-Validierung vor dem Schreiben
        scenarios.append(data)
    return scenarios


def write_scenarios(scenarios: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, data in enumerate(scenarios, start=1):
        path = out_dir / f"{i:02d}-{data['id']}.yaml"
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generiert Automotive-Kundendialoge (Szenario-YAMLs) fuer configs/auto-*.yaml")
    parser.add_argument("--count", type=int, default=12, help="Anzahl Szenarien (Default: 12)")
    parser.add_argument("--out", default="scenarios/auto", help="Zielverzeichnis")
    parser.add_argument("--seed", type=int, default=42, help="Zufalls-Seed (Reproduzierbarkeit)")
    parser.add_argument("--domains", default="navigation,entertainment,klima,kombi",
                        help="Kommagetrennt: navigation, entertainment, klima, kombi")
    args = parser.parse_args()

    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    scenarios = generate(args.count, domains, args.seed)
    paths = write_scenarios(scenarios, Path(args.out))

    print(f"{len(paths)} Szenarien nach {args.out}/ geschrieben:")
    for path, data in zip(paths, scenarios):
        tools = ", ".join(c["tool"] for c in data["success_criteria"].get("tool_calls", []))
        print(f"  {path.name:<28} erwartet: {tools}")
    print(f"\nAusfuehren mit:\n  python -m agent_eval run --config configs/auto-baseline.yaml "
          f"--scenarios {args.out}")


if __name__ == "__main__":
    main()
