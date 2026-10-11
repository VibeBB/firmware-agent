"""Write an intact VRP v2 decision and impression for liaison/request tests."""

from __future__ import annotations

import json
from pathlib import Path

from firmware import records

NOTES = "out/vrp-notes.md"
IMPRESSION = (
    "The harness drawing reads as a coherent build sheet: wire W1 runs from C1.1 to "
    "C2.1 and every cavity carries a unique label. What worries me is the 3.3 V sense "
    "lead, which runs parallel to the motor feed for most of its length and could pick "
    "up switching noise. A fabricator would still be able to cut and crimp from the "
    "tables alone, although the splice note is small. Next I would re-route the sense "
    "lead along the far edge of the bundle and re-render to confirm the separation. "
    "Overall the sheet communicates intent well, and the remaining risk sits in one "
    "routing choice."
)


def chained_refs(root: Path) -> tuple[str, str]:
    """Record one decision and one impression once; return their event ids."""
    logged = [
        records.records_dir(root) / records.LOG_FILES[kind]
        for kind in ("decision", "stage_impression")
    ]
    if all(log.is_file() for log in logged):
        first = [json.loads(log.read_text(encoding="utf-8").splitlines()[0]) for log in logged]
        return str(first[0]["event_id"]), str(first[1]["event_id"])
    notes = root / NOTES
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        "W1 runs from C1.1 to C2.1; the sense lead parallels the motor feed.\n",
        encoding="utf-8",
    )
    decision = records.record_decision(
        {
            "id": "sense-lead-routing",
            "stage": "design",
            "question": "Where should the 3.3 V sense lead run inside the bundle?",
            "principles": ["Inductive coupling falls with separation"],
            "options": [
                {"name": "same-bundle", "pros": ["shortest"], "cons": ["noise coupling"]},
                {"name": "far-edge", "pros": ["separation"], "cons": ["+40 mm length"]},
            ],
            "chosen": "far-edge",
            "rationale": (
                "The sense lead feeds an ADC whose LSB is about 0.8 mV, while the motor "
                "feed switches several amperes at 20 kHz; mutual inductance along a 300 mm "
                "parallel run would inject more than an LSB, so physical separation is the "
                "cheapest fix."
            ),
            "evidence": [{"path": NOTES}],
            "assumptions": ["motor PWM is 20 kHz"],
            "unknowns": ["actual motor current ripple"],
            "risks": ["longer lead adds 40 mm of copper"],
            "revisit_when": "a measured ADC noise floor exceeds 2 LSB",
        },
        root,
    )
    impression = records.record_impression(
        {
            "stage": "export",
            "artifacts": [NOTES],
            "impression": IMPRESSION,
            "facets": {
                "observed": ["W1 runs C1.1 to C2.1", "sense lead parallels the motor feed"],
                "works": ["cavity labels are unique"],
                "concerns": [
                    {
                        "id": "c1",
                        "text": "sense lead couples motor switching noise",
                        "severity": "warning",
                        "about": "self",
                        "anchor": "W1",
                    }
                ],
                "feelings": {
                    "maker": "can kit and crimp from the tables",
                    "user": "never sees it unless servicing",
                },
                "next_actions": ["re-route the sense lead along the far edge"],
            },
            "claims": [
                {"text": "wire W1 exists", "anchor": "W1", "artifact": NOTES},
                {"text": "C1.1 is the source cavity", "anchor": "C1.1", "artifact": NOTES},
            ],
            "confidence": "medium",
            "unknowns": ["actual motor current ripple"],
        },
        root,
    )
    return str(decision["record"]["event_id"]), str(impression["record"]["event_id"])
