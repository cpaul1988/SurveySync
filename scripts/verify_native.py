"""Reject missing/non-GUI native launchers after the Windows Go build."""

from pathlib import Path
import struct


def verify(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError(f"{path.name}: invalid executable header")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if offset + 94 > len(data) or data[offset : offset + 4] != b"PE\0\0":
        raise ValueError(f"{path.name}: invalid PE header")
    if struct.unpack_from("<H", data, offset + 4 + 20 + 68)[0] != 2:
        raise ValueError(f"{path.name}: expected Windows GUI subsystem")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    for name in ("SurveySync.exe", "SurveySyncUpdater.exe"):
        verify(root / name)
    print("Both native launchers passed PE/GUI verification.")
