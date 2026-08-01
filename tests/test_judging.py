"""Tests fuer Label-Vorlage und Kalibrierung (offline, ohne API)."""

import json

import yaml

from agent_eval.judging import calibrate, write_label_template


def _results(tmp_path):
    payload = {
        "config": {"id": "t", "judge": {"model": "claude-opus-5"}},
        "runs": [
            {"scenario": "s1", "rep": 1,
             "transcript": [{"role": "customer", "text": "Hallo"},
                            {"role": "assistant", "text": "Erledigt."}],
             "tool_calls": [],
             "judge": {"goal_achieved": True, "faithfulness": 5,
                       "conversation_quality": 4, "voice_suitability": 4,
                       "comment": ""}},
            {"scenario": "s2", "rep": 1,
             "transcript": [{"role": "customer", "text": "Hi"}],
             "tool_calls": [],
             "judge": {"goal_achieved": True, "faithfulness": 4,
                       "conversation_quality": 3, "voice_suitability": 5,
                       "comment": ""}},
        ],
    }
    path = tmp_path / "results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_label_template(tmp_path):
    results = _results(tmp_path)
    out = write_label_template(results, tmp_path / "labels.yaml")
    entries = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(entries) == 2
    assert entries[0]["run"] == "s1#1"
    assert "Kunde: Hallo" in entries[0]["transcript"]
    assert entries[0]["goal_achieved"] is None


def test_calibrate_agreement(tmp_path):
    results = _results(tmp_path)
    labels = [
        # Mensch widerspricht bei s1 (nicht erreicht), stimmt bei s2 zu
        {"run": "s1#1", "goal_achieved": False, "faithfulness": 3,
         "conversation_quality": 4, "voice_suitability": 4},
        {"run": "s2#1", "goal_achieved": True, "faithfulness": 4,
         "conversation_quality": 3, "voice_suitability": 5},
    ]
    labels_path = tmp_path / "labels.yaml"
    labels_path.write_text(yaml.safe_dump(labels), encoding="utf-8")

    stats = calibrate(results, labels_path)
    assert stats["paare"] == 2
    assert stats["goal_achieved"]["uebereinstimmung_pct"] == 50.0
    # faithfulness: |3-5|=2 und |4-4|=0 -> MAE 1.0, Judge im Schnitt +1 zu milde
    assert stats["faithfulness"]["mae"] == 1.0
    assert stats["faithfulness"]["bias"] == 1.0
    assert stats["conversation_quality"]["mae"] == 0.0
