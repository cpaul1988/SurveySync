from __future__ import annotations
import logging

import ctypes
import os
import platform
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Literal

from gpu_compat import evaluate_gpu

PerformanceMode = Literal["auto", "safe", "balanced", "high"]


@dataclass(frozen=True)
class HardwareProfile:
    logical_cores: int
    physical_cores: int
    total_ram_bytes: int
    available_ram_bytes: int
    platform: str
    nvidia_gpu: bool = False
    nvidia_gpu_name: str = ""
    nvidia_vram_bytes: int = 0
    nvidia_compute_capability: float = 0.0
    nvidia_driver_cuda: float = 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["total_ram_gb"] = round(self.total_ram_bytes / (1024 ** 3), 1) if self.total_ram_bytes else 0.0
        d["available_ram_gb"] = round(self.available_ram_bytes / (1024 ** 3), 1) if self.available_ram_bytes else 0.0
        d["nvidia_vram_gb"] = round(self.nvidia_vram_bytes / (1024 ** 3), 1) if self.nvidia_vram_bytes else 0.0
        compat = evaluate_gpu(
            present=self.nvidia_gpu,
            name=self.nvidia_gpu_name,
            vram_mib=int(self.nvidia_vram_bytes / (1024 ** 2)) if self.nvidia_vram_bytes else 0,
            compute_capability=self.nvidia_compute_capability,
            cuda_version=self.nvidia_driver_cuda,
        )
        d["paddle_windows_gpu_supported"] = compat.supported
        d["paddle_windows_gpu_channel"] = compat.channel
        d["paddle_windows_gpu_reason"] = compat.reason
        return d


@dataclass(frozen=True)
class PerformancePlan:
    requested_mode: str
    effective_mode: str
    enhancement_workers: int
    paddle_cpu_threads: int
    prefetch_pages: int
    cache_enabled: bool = True
    interpretation_cache_enabled: bool = True
    accuracy_first: bool = True
    enable_hpi: bool = True
    prefer_gpu: bool = True
    pipeline_overlap: bool = False
    qwen_workers: int = 1
    near_match_routing: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


def _memory_windows() -> tuple[int, int]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
    return 0, 0


def _memory_posix() -> tuple[int, int]:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        avail_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        return page_size * total_pages, page_size * avail_pages
    except (AttributeError, ValueError, OSError):
        return 0, 0


def _physical_cores(logical: int) -> int:
    try:
        import psutil  # type: ignore
        physical = psutil.cpu_count(logical=False)
        if physical:
            return max(1, int(physical))
    except Exception:
        logging.getLogger(__name__).warning("Recovery fallback in performance; operation did not complete.", exc_info=True)
    return max(1, logical // 2 if logical >= 4 else logical)


def _parse_float(value: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", value or "")
    return float(match.group(1)) if match else 0.0


def _detect_nvidia() -> tuple[bool, str, int, float, float]:
    """Best-effort NVIDIA inventory using nvidia-smi; never makes startup fail."""
    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
        if query.returncode != 0 or not query.stdout.strip():
            # Some older nvidia-smi builds do not expose compute_cap as a query
            # field. Fall back to the universally available name/memory inventory.
            query = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=3, check=False,
            )
        if query.returncode != 0 or not query.stdout.strip():
            return False, "", 0, 0.0, 0.0
        first = query.stdout.splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        name = parts[0] if parts else "NVIDIA GPU"
        vram_mib = int(float(parts[1])) if len(parts) > 1 and _parse_float(parts[1]) else 0
        compute_cap = _parse_float(parts[2]) if len(parts) > 2 else 0.0

        cuda_version = 0.0
        banner = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3, check=False,
        )
        if banner.returncode == 0:
            m = re.search(r"CUDA Version:\s*([0-9.]+)", banner.stdout or "", flags=re.I)
            if m:
                cuda_version = _parse_float(m.group(1))
        return True, name, vram_mib * 1024 * 1024, compute_cap, cuda_version
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, "", 0, 0.0, 0.0


def detect_hardware(*, include_gpu: bool = True) -> HardwareProfile:
    logical = max(1, int(os.cpu_count() or 1))
    physical = _physical_cores(logical)
    if os.name == "nt":
        total, available = _memory_windows()
    else:
        total, available = _memory_posix()
    if include_gpu:
        has_nv, gpu_name, vram, compute_cap, driver_cuda = _detect_nvidia()
    else:
        has_nv, gpu_name, vram, compute_cap, driver_cuda = False, "", 0, 0.0, 0.0
    return HardwareProfile(
        logical_cores=logical,
        physical_cores=physical,
        total_ram_bytes=max(0, total),
        available_ram_bytes=max(0, available),
        platform=f"{platform.system()} {platform.release()}".strip(),
        nvidia_gpu=has_nv,
        nvidia_gpu_name=gpu_name,
        nvidia_vram_bytes=max(0, vram),
        nvidia_compute_capability=max(0.0, compute_cap),
        nvidia_driver_cuda=max(0.0, driver_cuda),
    )


def _auto_effective(profile: HardwareProfile) -> str:
    avail_gb = profile.available_ram_bytes / (1024 ** 3) if profile.available_ram_bytes else 0
    total_gb = profile.total_ram_bytes / (1024 ** 3) if profile.total_ram_bytes else 0
    ram_gb = avail_gb or total_gb
    if profile.physical_cores >= 6 and ram_gb >= 12:
        return "high"
    if profile.physical_cores >= 4 and ram_gb >= 6:
        return "balanced"
    return "safe"


def build_performance_plan(mode: str = "auto", profile: HardwareProfile | None = None) -> PerformancePlan:
    """Build an accuracy-first throughput plan.

    v8.0.9 intentionally separates *safe* acceleration (threading, HPI, caches,
    prefetch) from risky shortcuts.  It never lowers source resolution, discards a
    nonblank page, or accepts a fuzzy PointID as final evidence.  Near matches are
    routing hints only and must be visually confirmed by Qwen or the normal full-page
    fallback.
    """
    profile = profile or detect_hardware()
    requested = (mode or "auto").strip().lower()
    if requested not in {"auto", "safe", "balanced", "high"}:
        requested = "auto"
    effective = _auto_effective(profile) if requested == "auto" else requested
    logical = profile.logical_cores
    physical = profile.physical_cores
    avail_gb = profile.available_ram_bytes / (1024 ** 3) if profile.available_ram_bytes else 0
    total_gb = profile.total_ram_bytes / (1024 ** 3) if profile.total_ram_bytes else 0
    ram_gb = avail_gb or total_gb

    if effective == "safe":
        enhance = 1
        paddle_threads = min(logical, 4)
        prefetch = 2
        hpi = False
    elif effective == "balanced":
        enhance = min(4, max(2, physical // 2))
        paddle_threads = min(logical, max(4, min(8, physical)))
        prefetch = 4 if avail_gb and avail_gb < 10 else 6
        hpi = True
    else:
        enhance = min(8, max(2, physical - 1))
        paddle_threads = min(logical, max(6, min(12, physical + max(1, physical // 2))))
        prefetch = 8
        if avail_gb >= 24:
            prefetch = 12
        elif avail_gb and avail_gb < 12:
            prefetch = 6
        hpi = True

    if profile.available_ram_bytes and profile.available_ram_bytes < 4 * 1024 ** 3:
        prefetch = min(prefetch, 2)
        enhance = min(enhance, 2)

    # Overlap is deliberately conservative.  The useful case is CPU Paddle + an
    # NVIDIA GPU available to Ollama.  Runtime makes the final decision after it
    # knows whether this specific Paddle environment is CPU or GPU.  This flag only
    # says the hardware is strong enough to consider overlap.
    overlap_capable = (
        effective == "high"
        and profile.nvidia_gpu
        and physical >= 6
        and ram_gb >= 12
    )

    return PerformancePlan(
        requested_mode=requested,
        effective_mode=effective,
        enhancement_workers=max(1, enhance),
        paddle_cpu_threads=max(1, paddle_threads),
        prefetch_pages=max(1, prefetch),
        cache_enabled=True,
        interpretation_cache_enabled=True,
        accuracy_first=True,
        enable_hpi=hpi,
        prefer_gpu=True,
        pipeline_overlap=overlap_capable,
        qwen_workers=1,
        near_match_routing=True,
    )
