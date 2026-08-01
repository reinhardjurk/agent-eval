"""CLI:

  python -m agent_eval run --config configs/baseline.yaml --scenarios scenarios --reps 3
  python -m agent_eval report results/baseline-opus5/results.json results/haiku-full-context/results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import report
from .runner import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent_eval")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Experiment ausfuehren")
    run.add_argument("--config", required=True, help="Pfad zur Experiment-YAML")
    run.add_argument("--scenarios", default="scenarios",
                     help="Szenario-Datei oder -Verzeichnis (Default: scenarios/)")
    run.add_argument("--reps", type=int, default=None,
                     help="Wiederholungen pro Szenario (Default: aus der Config)")
    run.add_argument("--out", default=None, help="Ausgabeverzeichnis (Default: results/<id>)")
    run.add_argument("--fake", action="store_true",
                     help="Pipeline-Durchstich ohne API-Aufrufe (Smoke-Test)")
    run.add_argument("--no-judge", action="store_true", help="LLM-Judge ueberspringen")

    cmp = sub.add_parser("report", help="Mehrere results.json zu einer Vergleichstabelle mergen")
    cmp.add_argument("results", nargs="+", help="Pfade zu results.json-Dateien")
    cmp.add_argument("--by-scenario", action="store_true",
                     help="Zusaetzlich Aufschluesselung pro Szenario ausgeben")

    jdg = sub.add_parser("judge", help="LLM-Judge nachtraeglich auf gespeicherte Laeufe anwenden")
    jdg.add_argument("--results", required=True, help="Pfad zur results.json")
    jdg.add_argument("--scenarios", default="scenarios",
                     help="Szenario-Verzeichnis des Laufs (fuer Ziel/Persona)")
    jdg.add_argument("--model", default=None,
                     help="Judge-Modell (Default: aus der Config des Laufs)")

    lbl = sub.add_parser("label", help="YAML-Vorlage fuer manuelle Annotation erzeugen")
    lbl.add_argument("--results", required=True, help="Pfad zur results.json")
    lbl.add_argument("--out", default=None,
                     help="Zieldatei (Default: labels.yaml neben der results.json)")

    cal = sub.add_parser("calibrate", help="Judge-Scores gegen manuelle Labels kalibrieren")
    cal.add_argument("--results", required=True, help="Pfad zur results.json (mit Judge-Scores)")
    cal.add_argument("--labels", required=True, help="Ausgefuellte Label-YAML")

    args = parser.parse_args()
    if args.command == "run":
        run_experiment(args.config, args.scenarios, reps=args.reps, out_dir=args.out,
                       fake=args.fake, judge_enabled=not args.no_judge)
    elif args.command == "report":
        payloads = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.results]
        markdown = report.render_summary(payloads)
        if args.by_scenario:
            markdown += report.render_by_scenario(payloads)
        markdown += report.render_failures(payloads)
        report.append_step_summary(markdown)
        print(markdown)
    elif args.command == "judge":
        from .judging import judge_results

        judge_results(Path(args.results), Path(args.scenarios), model=args.model)
    elif args.command == "label":
        from .judging import write_label_template

        out = Path(args.out) if args.out else Path(args.results).parent / "labels.yaml"
        write_label_template(Path(args.results), out)
    elif args.command == "calibrate":
        from .judging import calibrate

        calibrate(Path(args.results), Path(args.labels))


if __name__ == "__main__":
    main()
