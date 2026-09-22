from __future__ import annotations

from pathlib import Path

from gpu_compat import evaluate_gpu
from fieldbook_sync.performance import HardwareProfile

ROOT = Path(__file__).resolve().parents[1]
AUTO = (ROOT / "install_paddleocr_auto.bat").read_text(encoding="utf-8")
GPU = (ROOT / "Install_PaddleOCR_GPU_Optional.bat").read_text(encoding="utf-8")
LOCAL = (ROOT / "install_local_ai.bat").read_text(encoding="utf-8")
APP = (ROOT / "fieldbook_sync/app.py").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")


def test_v814_gtx1650_cc75_is_fail_closed_to_cpu():
    result = evaluate_gpu(
        present=True,
        name="NVIDIA GeForce GTX 1650 with Max-Q Design",
        vram_mib=4096,
        compute_capability=7.5,
        driver_version="999.1",
        cuda_version=12.9,
    )
    assert result.present is True
    assert result.supported is False
    assert result.channel == ""
    assert "over 7.5" in result.reason


def test_v814_official_windows_channels_are_selected_only_after_support():
    assert evaluate_gpu(present=True, compute_capability=8.6, cuda_version=11.8).channel == "cu118"
    assert evaluate_gpu(present=True, compute_capability=8.6, cuda_version=12.6).channel == "cu126"
    assert evaluate_gpu(present=True, compute_capability=8.6, cuda_version=12.9).channel == "cu129"


def test_v814_missing_capability_or_cuda_never_guesses_gpu():
    missing_cc = evaluate_gpu(present=True, name="NVIDIA", compute_capability=0, cuda_version=12.9)
    missing_cuda = evaluate_gpu(present=True, name="NVIDIA", compute_capability=8.6, cuda_version=0)
    old_cuda = evaluate_gpu(present=True, name="NVIDIA", compute_capability=8.6, cuda_version=11.7)
    assert not missing_cc.supported and missing_cc.channel == ""
    assert not missing_cuda.supported and missing_cuda.channel == ""
    assert not old_cuda.supported and old_cuda.channel == ""


def test_v814_hardware_summary_exposes_windows_paddle_eligibility():
    old = HardwareProfile(
        logical_cores=12, physical_cores=6, total_ram_bytes=16 * 1024**3,
        available_ram_bytes=8 * 1024**3, platform="Windows 11", nvidia_gpu=True,
        nvidia_gpu_name="GTX 1650", nvidia_vram_bytes=4 * 1024**3,
        nvidia_compute_capability=7.5, nvidia_driver_cuda=12.9,
    ).as_dict()
    new = HardwareProfile(
        logical_cores=16, physical_cores=8, total_ram_bytes=32 * 1024**3,
        available_ram_bytes=20 * 1024**3, platform="Windows 11", nvidia_gpu=True,
        nvidia_gpu_name="RTX", nvidia_vram_bytes=8 * 1024**3,
        nvidia_compute_capability=8.6, nvidia_driver_cuda=12.6,
    ).as_dict()
    assert old["paddle_windows_gpu_supported"] is False
    assert new["paddle_windows_gpu_supported"] is True
    assert new["paddle_windows_gpu_channel"] == "cu126"


def test_v814_all_paddle_entrypoints_share_auto_probe():
    assert "install_paddleocr_auto.bat" in LOCAL
    assert "probe_paddle_gpu.py" in AUTO
    assert "Install_PaddleOCR_GPU_Optional.bat" in AUTO
    assert "install_paddleocr_local.bat" in AUTO
    assert "probe_paddle_gpu.py" in GPU
    assert "install_paddleocr_auto.bat" in APP


def test_v814_gpu_installer_blocks_missing_values_and_does_real_gpu_work():
    assert 'if not defined GPU_CHANNEL goto :probe_failed' in GPU
    assert 'if not defined GPU_CUDA_VERSION goto :probe_failed' in GPU
    assert 'if not defined GPU_COMPUTE_CAP goto :probe_failed' in GPU
    assert "paddle.set_device('gpu:0')" in GPU
    assert "x=paddle.to_tensor([1.0,2.0])" in GPU
    assert "The existing .paddleenv was NOT replaced" in GPU


def test_v814_ui_does_not_imply_all_nvidia_gpus_support_paddle_gpu():
    assert "paddle_windows_gpu_supported" in JS
    assert "Paddle OCR will stay on CPU" in JS
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "8.1.21"
