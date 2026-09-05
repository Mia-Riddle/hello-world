"""Quick, honest micro-benchmarks.

No fake numbers and no comparison against a mystery global database -- just
measuring what this machine can actually do right now, so it can be compared
against what a specific editing workflow needs (see workload.py), and so it
can be tracked over time across saved builds (see build_store.py).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from typing import Optional


@dataclass
class BenchmarkResults:
    cpu_hash_mb_per_sec: float
    ram_copy_gb_per_sec: float
    disk_write_mb_per_sec: float
    disk_read_mb_per_sec: float


def _hash_worker(duration_sec: float) -> int:
    """Hashes 1MB chunks for `duration_sec` seconds, returns MB processed."""
    chunk = os.urandom(1024 * 1024)
    end = time.time() + duration_sec
    processed = 0
    while time.time() < end:
        hashlib.sha256(chunk).digest()
        processed += 1
    return processed


def benchmark_cpu(duration_sec: float = 2.0, workers: Optional[int] = None) -> float:
    """Multi-core SHA-256 throughput in MB/sec, using all logical cores by default."""
    workers = workers or cpu_count()
    with Pool(workers) as pool:
        results = pool.map(_hash_worker, [duration_sec] * workers)
    return round(sum(results) / duration_sec, 1)


def benchmark_ram(size_mb: int = 256, repeats: int = 5) -> float:
    """Memory copy bandwidth in GB/sec. Uses numpy if available, else pure Python."""
    try:
        import numpy as np
        src = np.frombuffer(os.urandom(size_mb * 1024 * 1024), dtype=np.uint8)
        start = time.perf_counter()
        for _ in range(repeats):
            _ = src.copy()
        elapsed = time.perf_counter() - start
    except ImportError:
        data = os.urandom(size_mb * 1024 * 1024)
        start = time.perf_counter()
        for _ in range(repeats):
            _ = bytearray(data)
        elapsed = time.perf_counter() - start
    total_gb = (size_mb * repeats) / 1024
    return round(total_gb / elapsed, 2)


def benchmark_disk(target_dir: str, size_mb: int = 512):
    """Sequential write/read speed in MB/sec against a temp file in target_dir.

    The read pass can be inflated by OS page caching; treat this as a solid
    real-world estimate, not a lab-grade measurement.
    """
    os.makedirs(target_dir, exist_ok=True)
    block = os.urandom(1024 * 1024)
    fd, path = tempfile.mkstemp(dir=target_dir, prefix="pcbench_")
    try:
        start = time.perf_counter()
        with os.fdopen(fd, "wb") as f:
            for _ in range(size_mb):
                f.write(block)
            f.flush()
            os.fsync(f.fileno())
        write_speed = round(size_mb / (time.perf_counter() - start), 1)

        start = time.perf_counter()
        with open(path, "rb") as f:
            while f.read(4 * 1024 * 1024):
                pass
        read_speed = round(size_mb / (time.perf_counter() - start), 1)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return write_speed, read_speed


def run_all_benchmarks(disk_target_dir: str) -> BenchmarkResults:
    cpu = benchmark_cpu()
    ram = benchmark_ram()
    write_speed, read_speed = benchmark_disk(disk_target_dir)
    return BenchmarkResults(
        cpu_hash_mb_per_sec=cpu,
        ram_copy_gb_per_sec=ram,
        disk_write_mb_per_sec=write_speed,
        disk_read_mb_per_sec=read_speed,
    )
