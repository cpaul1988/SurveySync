from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import asdict, dataclass


MIN_WINDOWS_PADDLE_CC_EXCLUSIVE = 7.5
MIN_CUDA = 11.8
PADDLE_VERSION = "3.3.0"


@dataclass(frozen=True)
class PaddleGpuCompatibility:
    present: bool = False
    name: str = ""
    vram_mib: int = 0
    compute_capability: float = 0.0
    driver_version: str = ""
    cuda_version: float = 0.0
    supported: bool = False
    channel: str = ""
    paddle_version: str = PADDLE_VERSION
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _number(text: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(match.group(1)) if match else 0.0


def _int_number(text: str) -> int:
    value = _number(text)
    return int(value) if value else 0


def _channel_for_cuda(cuda_version: float) -> str:
    if cuda_version >= 12.9:
        return "cu129"
    if cuda_version >= 12.6:
        return "cu126"
    if cuda_version >= 11.8:
        return "cu118"
    return ""


def evaluate_gpu(
    *,
    present: bool,
    name: str = "",
    vram_mib: int = 0,
    compute_capability: float = 0.0,
    driver_version: str = "",
    cuda_version: float = 0.0,
) -> PaddleGpuCompatibility:
    """Evaluate support for the *official current Windows PaddlePaddle GPU wheel*.

    PaddleOCR-VL itself documents PaddlePaddle inference at CC >= 7.0 / CUDA >= 11.8,
    but the current PaddlePaddle 3.3 Windows pip installation guide requires GPU compute
    capability *over* 7.5.  FieldBook Sync follows the stricter Windows wheel rule so
    installation is fail-safe on Windows machines such as GTX 1650 (CC 7.5).
    """
    if not present:
        return PaddleGpuCompatibility(reason="No NVIDIA GPU/driver was detected by nvidia-smi.")
    if compute_capability <= 0:
        return PaddleGpuCompatibility(
            present=True, name=name, vram_mib=vram_mib, driver_version=driver_version,
            cuda_version=cuda_version,
            reason="NVIDIA compute capability could not be detected; GPU installation is blocked rather than guessed.",
        )
    if compute_capability <= MIN_WINDOWS_PADDLE_CC_EXCLUSIVE:
        return PaddleGpuCompatibility(
            present=True, name=name, vram_mib=vram_mib, compute_capability=compute_capability,
            driver_version=driver_version, cuda_version=cuda_version,
            reason=(
                f"Current official PaddlePaddle {PADDLE_VERSION} Windows GPU wheels require compute "
                f"capability over {MIN_WINDOWS_PADDLE_CC_EXCLUSIVE:.1f}; this GPU reports "
                f"{compute_capability:.1f}. Use the CPU PaddleOCR runtime."
            ),
        )
    if cuda_version <= 0:
        return PaddleGpuCompatibility(
            present=True, name=name, vram_mib=vram_mib, compute_capability=compute_capability,
            driver_version=driver_version,
            reason="The NVIDIA driver's supported CUDA version could not be detected; GPU installation is blocked rather than guessed.",
        )
    channel = _channel_for_cuda(cuda_version)
    if not channel:
        return PaddleGpuCompatibility(
            present=True, name=name, vram_mib=vram_mib, compute_capability=compute_capability,
            driver_version=driver_version, cuda_version=cuda_version,
            reason=f"The NVIDIA driver reports CUDA {cuda_version:.1f}; CUDA {MIN_CUDA:.1f} or newer is required.",
        )
    return PaddleGpuCompatibility(
        present=True,
        name=name,
        vram_mib=vram_mib,
        compute_capability=compute_capability,
        driver_version=driver_version,
        cuda_version=cuda_version,
        supported=True,
        channel=channel,
        reason=f"Compatible with the official PaddlePaddle {PADDLE_VERSION} Windows {channel} GPU wheel.",
    )


def probe_nvidia(timeout: float = 5.0) -> PaddleGpuCompatibility:
    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,compute_cap,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        has_compute = True
        if query.returncode != 0 or not query.stdout.strip():
            # Older nvidia-smi releases may not expose compute_cap as a query field.
            # Keep the GPU visible but block GPU installation rather than guessing CC.
            has_compute = False
            query = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        if query.returncode != 0 or not query.stdout.strip():
            return evaluate_gpu(present=False)

        cuda_version = 0.0
        banner = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if banner.returncode == 0:
            match = re.search(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", banner.stdout or "", flags=re.I)
            if match:
                cuda_version = _number(match.group(1))

        candidates: list[PaddleGpuCompatibility] = []
        for line in query.stdout.splitlines():
            if not line.strip():
                continue
            parts = [part.strip() for part in line.split(",")]
            name = parts[0] if parts else "NVIDIA GPU"
            vram_mib = _int_number(parts[1]) if len(parts) > 1 else 0
            if has_compute:
                compute_capability = _number(parts[2]) if len(parts) > 2 else 0.0
                driver_version = parts[3] if len(parts) > 3 else ""
            else:
                compute_capability = 0.0
                driver_version = parts[2] if len(parts) > 2 else ""
            candidates.append(
                evaluate_gpu(
                    present=True,
                    name=name,
                    vram_mib=vram_mib,
                    compute_capability=compute_capability,
                    driver_version=driver_version,
                    cuda_version=cuda_version,
                )
            )
        if not candidates:
            return evaluate_gpu(present=False)
        supported = [item for item in candidates if item.supported]
        if supported:
            return max(supported, key=lambda item: (item.vram_mib, item.compute_capability))
        return max(candidates, key=lambda item: (item.compute_capability, item.vram_mib))
    except (OSError, subprocess.SubprocessError, ValueError):
        return evaluate_gpu(present=False)


def _sanitize_env(value: str) -> str:
    # Output is parsed by cmd.exe as KEY=VALUE. Keep it one line and avoid metacharacters.
    return re.sub(r"[\r\n&|<>^]", " ", str(value or "")).strip()


def print_env(result: PaddleGpuCompatibility) -> None:
    values = {
        "PRESENT": "1" if result.present else "0",
        "NAME": result.name,
        "VRAM_MIB": str(result.vram_mib),
        "COMPUTE_CAP": f"{result.compute_capability:.1f}" if result.compute_capability else "",
        "DRIVER_VERSION": result.driver_version,
        "CUDA_VERSION": f"{result.cuda_version:.1f}" if result.cuda_version else "",
        "SUPPORTED": "1" if result.supported else "0",
        "CHANNEL": result.channel,
        "PADDLE_VERSION": result.paddle_version,
        "REASON": result.reason,
    }
    for key, value in values.items():
        print(f"{key}={_sanitize_env(value)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe NVIDIA compatibility for FieldBook Sync PaddleOCR on Windows.")
    parser.add_argument("--env", action="store_true", help="Print cmd.exe-friendly KEY=VALUE lines.")
    args = parser.parse_args()
    result = probe_nvidia()
    if args.env:
        print_env(result)
    else:
        print(result.as_dict())
    return 0 if result.supported else 2


if __name__ == "__main__":
    raise SystemExit(main())
