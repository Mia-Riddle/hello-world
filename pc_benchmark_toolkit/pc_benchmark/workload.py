"""Turns a plain description of your editing workflow into concrete hardware
targets (threads, RAM, VRAM, sustained storage speed).

The formulas are engineering rules of thumb -- decode cost by codec, bitrate-
driven storage needs, VRAM by resolution -- not a number pulled from someone
else's database. They live in data/workload_rules.json, so you can open that
file and tune it as your workflow (or opinion of it) changes.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

RULES_PATH = Path(__file__).parent / "data" / "workload_rules.json"


def load_rules() -> dict:
    with open(RULES_PATH) as f:
        return json.load(f)


@dataclass
class WorkflowAnswers:
    resolution: str
    codec: str
    multicam_streams: int
    grading_intensity: str


@dataclass
class Requirements:
    min_threads: int
    comfortable_threads: int
    min_ghz: float
    recommended_ram_gb: int
    recommended_gpu_vram_gb: float
    min_storage_mb_s: float
    demand_explanation: list


def compute_requirements(answers: WorkflowAnswers, rules: dict = None) -> Requirements:
    rules = rules or load_rules()
    res_factor = rules["resolution_factor"][answers.resolution]
    codec = rules["codecs"][answers.codec]
    grading = rules["grading_factor"][answers.grading_intensity]
    streams = max(1, answers.multicam_streams)
    effective_streams = 1 + (streams - 1) * 0.6

    cpu_units = res_factor * codec["cpu_factor"] * effective_streams
    min_threads = max(4, math.ceil(cpu_units * rules["cpu_threads_per_unit_min"]))
    comfortable_threads = max(min_threads, math.ceil(cpu_units * rules["cpu_threads_per_unit_comfortable"]))
    min_ghz = (rules["min_ghz_raw_or_multicam"]
               if (answers.codec == "raw_braw_red" or streams > 1)
               else rules["min_ghz_base"])

    ram_raw = (rules["ram_base_gb"] + res_factor * rules["ram_per_unit_gb"]
               + streams * rules["ram_per_stream_gb"] + codec["ram_add_gb"])
    supported = rules["supported_ram_sizes_gb"]
    recommended_ram_gb = next((s for s in supported if s >= ram_raw), supported[-1])

    base_vram = rules["base_gpu_vram_gb"][answers.resolution]
    recommended_gpu_vram_gb = round(
        base_vram * codec["gpu_factor"] * grading * (1 + (streams - 1) * 0.15), 1
    )

    bitrate_mbps = (codec["bitrate_mbps_at_4k"]
                    * (res_factor / rules["resolution_factor"]["4k"]) * streams)
    min_storage_mb_s = round((bitrate_mbps / 8) * rules["storage_headroom_multiplier"], 1)

    explanation = [
        f"Resolution '{answers.resolution}' -> pixel-load factor {res_factor}x (vs. 1080p).",
        f"Codec '{codec['label']}' -> CPU decode factor {codec['cpu_factor']}x, GPU factor {codec['gpu_factor']}x.",
        f"{streams} concurrent stream(s) -> effective multiplier {effective_streams:.2f}x on CPU/GPU.",
        f"Grading intensity '{answers.grading_intensity}' -> GPU factor {grading}x.",
        f"Estimated sustained footage bitrate ~{bitrate_mbps:.0f} Mbps -> "
        f"{min_storage_mb_s} MB/s storage needed (with {rules['storage_headroom_multiplier']}x headroom).",
    ]

    return Requirements(
        min_threads=min_threads,
        comfortable_threads=comfortable_threads,
        min_ghz=min_ghz,
        recommended_ram_gb=recommended_ram_gb,
        recommended_gpu_vram_gb=recommended_gpu_vram_gb,
        min_storage_mb_s=min_storage_mb_s,
        demand_explanation=explanation,
    )
