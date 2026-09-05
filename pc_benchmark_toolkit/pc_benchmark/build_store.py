"""Save/load PC snapshots so you can track how your machine (and your budget)
changes over time -- e.g. compare before/after your next upgrade.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

BUILDS_DIR = Path(__file__).parent.parent / "saved_builds"


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.strip().lower()).strip("-") or "build"


def save_build(name: str, snapshot, bench, answers, req, evaluation, suggestions) -> Path:
    BUILDS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BUILDS_DIR / f"{_slugify(name)}-{timestamp}.json"

    data = {
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "hardware": asdict(snapshot),
        "benchmark": asdict(bench),
        "workflow_answers": asdict(answers),
        "requirements": asdict(req),
        "evaluation": [{**asdict(v), "status": v.status.value} for v in evaluation.verdicts],
        "upgrade_suggestions": [asdict(s) for s in suggestions],
        "estimated_upgrade_total_usd": round(sum(s.price_usd for s in suggestions), 2),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def list_builds():
    if not BUILDS_DIR.exists():
        return []
    return sorted(BUILDS_DIR.glob("*.json"), reverse=True)


def load_build(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)
