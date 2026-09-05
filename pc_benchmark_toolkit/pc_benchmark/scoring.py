"""Compares a real hardware scan + benchmark against computed requirements.

Every verdict here traces back to a number you can see and a formula you can
read in workload.py -- the opposite of a black-box global percentile score.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    GOOD = "GOOD"
    WARN = "WARN"
    BAD = "BAD"
    INFO = "INFO"


@dataclass
class ComponentVerdict:
    category: str
    status: Status
    summary: str
    detail: str


@dataclass
class Evaluation:
    verdicts: list = field(default_factory=list)

    @property
    def bottlenecks(self):
        return [v for v in self.verdicts if v.status in (Status.WARN, Status.BAD)]


def evaluate(snapshot, bench, req) -> Evaluation:
    verdicts = []

    # CPU: real spec (thread count) vs computed target. The hash benchmark is
    # reported alongside as a real-world number to track across saved builds,
    # since there's no grounded absolute threshold for it.
    threads = snapshot.logical_cores
    if threads >= req.comfortable_threads:
        status = Status.GOOD
        summary = f"{threads} threads comfortably clears the {req.comfortable_threads}-thread target."
    elif threads >= req.min_threads:
        status = Status.WARN
        summary = (f"{threads} threads meets the bare minimum ({req.min_threads}) "
                   f"but not the comfortable target ({req.comfortable_threads}).")
    else:
        status = Status.BAD
        summary = f"{threads} threads is below the {req.min_threads}-thread minimum for this workflow."
    verdicts.append(ComponentVerdict(
        "CPU", status, summary,
        f"Measured hashing throughput: {bench.cpu_hash_mb_per_sec} MB/s "
        f"(save builds over time to see upgrades pay off).",
    ))

    # RAM
    if snapshot.ram_total_gb >= req.recommended_ram_gb:
        status = Status.GOOD
        summary = f"{snapshot.ram_total_gb}GB installed meets the {req.recommended_ram_gb}GB target."
    elif snapshot.ram_total_gb >= req.recommended_ram_gb * 0.75:
        status = Status.WARN
        summary = (f"{snapshot.ram_total_gb}GB is a bit under the {req.recommended_ram_gb}GB target "
                   f"-- expect some swapping/cache pressure.")
    else:
        status = Status.BAD
        summary = f"{snapshot.ram_total_gb}GB is well under the {req.recommended_ram_gb}GB target for this workflow."
    verdicts.append(ComponentVerdict(
        "RAM", status, summary,
        f"Measured memory copy bandwidth: {bench.ram_copy_gb_per_sec} GB/s.",
    ))

    # GPU: VRAM is the concrete comparable number. GPU name is informational.
    if snapshot.gpu_vram_gb is None:
        verdicts.append(ComponentVerdict(
            "GPU", Status.INFO,
            f"VRAM unknown for '{snapshot.gpu_name}' -- enter it manually from the main menu for a real verdict.",
            f"Target for this workflow: {req.recommended_gpu_vram_gb}GB VRAM.",
        ))
    else:
        if snapshot.gpu_vram_gb >= req.recommended_gpu_vram_gb:
            status = Status.GOOD
            summary = f"{snapshot.gpu_vram_gb}GB VRAM meets the {req.recommended_gpu_vram_gb}GB target."
        elif snapshot.gpu_vram_gb >= req.recommended_gpu_vram_gb * 0.7:
            status = Status.WARN
            summary = (f"{snapshot.gpu_vram_gb}GB VRAM is under the {req.recommended_gpu_vram_gb}GB target "
                       f"-- watch for dropped GPU effects/noise reduction.")
        else:
            status = Status.BAD
            summary = f"{snapshot.gpu_vram_gb}GB VRAM is well under the {req.recommended_gpu_vram_gb}GB target for this workflow."
        verdicts.append(ComponentVerdict("GPU", status, summary, f"GPU: {snapshot.gpu_name}"))

    # Storage: the one fully apples-to-apples comparison -- measured MB/s vs
    # bitrate-derived MB/s need.
    read_speed = bench.disk_read_mb_per_sec
    if read_speed >= req.min_storage_mb_s * 1.3:
        status = Status.GOOD
        summary = f"{read_speed} MB/s sustained read comfortably clears the {req.min_storage_mb_s} MB/s this footage needs."
    elif read_speed >= req.min_storage_mb_s:
        status = Status.WARN
        summary = (f"{read_speed} MB/s sustained read just meets the {req.min_storage_mb_s} MB/s needed "
                   f"-- little headroom for multicam or fast scrubbing.")
    else:
        status = Status.BAD
        summary = f"{read_speed} MB/s sustained read is below the {req.min_storage_mb_s} MB/s this footage needs -- expect dropped frames."
    verdicts.append(ComponentVerdict(
        "Storage", status, summary,
        f"Measured write: {bench.disk_write_mb_per_sec} MB/s. "
        f"(Tested on the drive you pointed the benchmark at -- test your media drive, not just your OS drive.)",
    ))

    return Evaluation(verdicts=verdicts)
