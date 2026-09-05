"""Hardware detection: figures out what's actually in this PC.

GPU VRAM in particular is unreliable to auto-detect without vendor SDKs or
admin rights, so callers should let the user fill it in manually when
`gpu_detected_automatically` is False.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import psutil


@dataclass
class DiskInfo:
    device: str
    mountpoint: str
    total_gb: float
    fstype: str


@dataclass
class HardwareSnapshot:
    os_name: str
    cpu_name: str
    physical_cores: int
    logical_cores: int
    cpu_max_ghz: Optional[float]
    ram_total_gb: float
    disks: list = field(default_factory=list)
    gpu_name: str = "Unknown (enter manually)"
    gpu_vram_gb: Optional[float] = None
    gpu_detected_automatically: bool = False


def _cpu_name() -> str:
    name = platform.processor()
    if name:
        return name
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "Unknown CPU"


def _cpu_max_ghz() -> Optional[float]:
    freq = psutil.cpu_freq()
    if freq and freq.max:
        return round(freq.max / 1000, 2)
    return None


def _disks() -> list:
    disks = []
    for part in psutil.disk_partitions(all=False):
        if not part.mountpoint:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(DiskInfo(
            device=part.device,
            mountpoint=part.mountpoint,
            total_gb=round(usage.total / (1024 ** 3), 1),
            fstype=part.fstype,
        ))
    return disks


def _detect_gpu():
    """Best-effort GPU detection. Returns (name, vram_gb, auto_detected)."""
    system = platform.system()

    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                text=True, timeout=5,
            ).strip()
            if out:
                name, mem = [p.strip() for p in out.splitlines()[0].split(",")]
                vram_gb = round(float(mem.replace("MiB", "").strip()) / 1024, 1)
                return name, vram_gb, True
        except Exception:
            pass

    if system == "Windows":
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                text=True, timeout=5,
            )
            lines = [l.strip() for l in out.splitlines() if l.strip() and "Name" not in l]
            if lines:
                return lines[0], None, True
        except Exception:
            pass

    if system == "Darwin":
        try:
            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"], text=True, timeout=10,
            )
            for line in out.splitlines():
                if "Chipset Model" in line:
                    return line.split(":", 1)[1].strip(), None, True
        except Exception:
            pass

    if system == "Linux":
        try:
            out = subprocess.check_output(["lspci"], text=True, timeout=5)
            for line in out.splitlines():
                if "VGA compatible controller" in line or "3D controller" in line:
                    return line.split(":", 2)[-1].strip(), None, True
        except Exception:
            pass

    return "Unknown (enter manually)", None, False


def scan_hardware() -> HardwareSnapshot:
    """Scans the current machine. GPU VRAM often needs a manual top-up."""
    gpu_name, gpu_vram, auto = _detect_gpu()
    return HardwareSnapshot(
        os_name=f"{platform.system()} {platform.release()}",
        cpu_name=_cpu_name(),
        physical_cores=psutil.cpu_count(logical=False) or 1,
        logical_cores=psutil.cpu_count(logical=True) or 1,
        cpu_max_ghz=_cpu_max_ghz(),
        ram_total_gb=round(psutil.virtual_memory().total / (1024 ** 3), 1),
        disks=_disks(),
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram,
        gpu_detected_automatically=auto,
    )
