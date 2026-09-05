"""Loads the editable parts/price catalog and turns bottlenecks into concrete
shopping suggestions with a running total.

Prices in data/parts_catalog.json are estimates you maintain yourself -- see
its "last_verified" field. Shopping links are search-result URLs (not deep
links to a specific listing), so they stay valid even as exact prices move.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

CATALOG_PATH = Path(__file__).parent / "data" / "parts_catalog.json"

SEARCH_TEMPLATES = {
    "B&H Photo": "https://www.bhphotovideo.com/c/search?q={q}",
    "Newegg": "https://www.newegg.com/p/pl?d={q}",
    "Amazon": "https://www.amazon.com/s?k={q}",
}


def load_catalog(path: Path = None) -> dict:
    with open(path or CATALOG_PATH) as f:
        return json.load(f)


def shop_links(part_name: str) -> dict:
    q = quote_plus(part_name)
    return {store: template.format(q=q) for store, template in SEARCH_TEMPLATES.items()}


@dataclass
class UpgradeSuggestion:
    category: str
    reason: str
    part_name: str
    price_usd: float
    note: str
    shop_links: dict


def _cheapest_meeting(parts, key: str, target: float):
    candidates = [p for p in parts if p[key] >= target]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p["price_usd"])


def suggest_upgrades(evaluation, snapshot, req, catalog: dict = None):
    catalog = catalog or load_catalog()
    suggestions = []

    for verdict in evaluation.bottlenecks:
        cat = verdict.category
        if cat == "CPU":
            part = _cheapest_meeting(catalog["cpu"], "threads", req.comfortable_threads)
        elif cat == "RAM":
            part = _cheapest_meeting(catalog["ram"], "ram_gb", req.recommended_ram_gb)
        elif cat == "GPU":
            part = _cheapest_meeting(catalog["gpu"], "vram_gb", req.recommended_gpu_vram_gb)
        elif cat == "Storage":
            part = _cheapest_meeting(catalog["storage"], "sequential_mb_s", req.min_storage_mb_s * 1.3)
        else:
            part = None

        if part is None:
            continue

        suggestions.append(UpgradeSuggestion(
            category=cat,
            reason=verdict.summary,
            part_name=part["name"],
            price_usd=part["price_usd"],
            note=part.get("note", ""),
            shop_links=shop_links(part["name"]),
        ))

    return suggestions


def total_cost(suggestions) -> float:
    return round(sum(s.price_usd for s in suggestions), 2)
