"""Convert numeric Windows .res metadata to a Go-compatible AMD64 COFF object.

Microsoft RC remains the resource compiler. This replaces only CVTRES's object
wrapper, whose absolute compiler symbols are rejected by Go's internal linker.
Resource payloads (icon, version and asInvoker manifest) are copied unchanged.
No executable is patched, packed, stripped, or run. No external dependencies.

Formats: https://learn.microsoft.com/en-us/windows/win32/menurc/resource-file-formats
         https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import struct

MAX_BYTES = 16 * 1024 * 1024
MAX_RESOURCES = 4096
SUPPORTED_TYPES = frozenset({3, 14, 16, 24})  # icon, icon group, version, manifest


@dataclass(frozen=True, order=True)
class Resource:
    kind: int
    name: int
    language: int
    data: bytes


def align4(size: int) -> int:
    return (size + 3) & ~3


def parse_res(raw: bytes) -> list[Resource]:
    """Accept our bounded, numeric-only RC output; reject unsupported input."""
    if not 32 <= len(raw) <= MAX_BYTES:
        raise ValueError("Resource input is empty, truncated, or oversized")
    offset = 0
    result: list[Resource] = []
    seen: set[tuple[int, int, int]] = set()
    while offset < len(raw):
        if offset + 32 > len(raw):
            raise ValueError("Truncated resource header")
        size, header, type_marker, kind, name_marker, name = struct.unpack_from(
            "<IIHHHH", raw, offset
        )
        if header != 32 or type_marker != 0xFFFF or name_marker != 0xFFFF:
            raise ValueError("Only numeric resource identifiers and 32-byte headers are supported")
        data_version, flags, language, version, characteristics = struct.unpack_from(
            "<IHHII", raw, offset + 16
        )
        end = offset + header + size
        padded_end = align4(end)
        if end > len(raw) or padded_end > len(raw):
            raise ValueError("Truncated resource payload or padding")
        if any(raw[end:padded_end]):
            raise ValueError("Nonzero resource padding")
        if offset == 0:
            if (size, kind, name, data_version, flags, language, version, characteristics) != (0,) * 8:
                raise ValueError("Missing Windows .res null header")
        else:
            key = (kind, name, language)
            if kind not in SUPPORTED_TYPES or name == 0 or size == 0:
                raise ValueError("Unsupported or empty resource")
            if data_version or version or characteristics:
                raise ValueError("Unsupported nonzero resource metadata")
            if key in seen:
                raise ValueError("Duplicate type/name/language resource")
            seen.add(key)
            result.append(Resource(kind, name, language, raw[offset + header:end]))
            if len(result) > MAX_RESOURCES:
                raise ValueError("Too many resources")
        offset = padded_end
    if not result:
        raise ValueError("Resource input has no metadata")
    return sorted(result)


def to_coff(resources: list[Resource]) -> bytes:
    """Emit one read-only .rsrc section with standard ADDR32NB relocations."""
    if not resources or len(resources) > MAX_RESOURCES:
        raise ValueError("Invalid resource count")
    # The tree has the PE-specified type -> name -> language -> data levels.
    tree: dict = {}
    for item in sorted(resources):
        if item.kind not in SUPPORTED_TYPES or not 1 <= item.name <= 65535:
            raise ValueError("Invalid resource identifier")
        if not 0 <= item.language <= 65535 or not item.data:
            raise ValueError("Invalid language or empty resource")
        languages = tree.setdefault(item.kind, {}).setdefault(item.name, {})
        if item.language in languages:
            raise ValueError("Duplicate resource")
        languages[item.language] = item.data
    if sum(len(x.data) for x in resources) > MAX_BYTES:
        raise ValueError("Resource payload limit exceeded")
    section = bytearray()
    relocations: list[int] = []
    leaves: list[tuple[int, bytes]] = []

    def directory(node: dict) -> int:
        position = len(section)
        entries = sorted(node.items())
        section.extend(struct.pack("<IIHHHH", 0, 0, 0, 0, 0, len(entries)))
        section.extend(bytes(8 * len(entries)))
        for index, (identifier, child) in enumerate(entries):
            if isinstance(child, dict):
                target = directory(child) | 0x80000000
            else:
                target = len(section)
                section.extend(bytes(16))
                leaves.append((target, child))
            struct.pack_into("<II", section, position + 16 + 8 * index, identifier, target)
        return position

    directory(tree)
    for entry, payload in leaves:
        section.extend(bytes(align4(len(section)) - len(section)))
        struct.pack_into("<IIII", section, entry, len(section), len(payload), 0, 0)
        relocations.append(entry)
        section.extend(payload)
    section.extend(bytes(align4(len(section)) - len(section)))
    data_offset = 60  # 20-byte COFF header + one 40-byte section header
    reloc_offset = data_offset + len(section)
    symbol_offset = reloc_offset + 10 * len(relocations)
    header = struct.pack("<HHIIIHH", 0x8664, 1, 0, symbol_offset, 2, 0, 0)
    section_header = struct.pack(
        "<8sIIIIIIHHI", b".rsrc", 0, 0, len(section), data_offset,
        reloc_offset, 0, len(relocations), 0, 0x40300040,
    )
    relocation_table = b"".join(struct.pack("<IIH", entry, 0, 3) for entry in relocations)
    # Static section symbol, positive section number, plus its section-definition
    # auxiliary record. No absolute compiler symbols or executable code exist.
    symbol = struct.pack("<8sIhHBB", b".rsrc", 0, 1, 0, 3, 1)
    auxiliary = struct.pack("<IHHIhBBH", len(section), len(relocations), 0, 0, 0, 0, 0, 0)
    return header + section_header + section + relocation_table + symbol + auxiliary + struct.pack("<I", 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        raise ValueError("Input and output must differ")
    if args.source.stat().st_size > MAX_BYTES:
        raise ValueError("Resource input exceeds size limit")
    resources = parse_res(args.source.read_bytes())
    result = to_coff(resources)
    args.destination.write_bytes(result)
    print(f"Wrote AMD64 COFF metadata: {len(resources)} resources, {len(result)} bytes")


if __name__ == "__main__":
    main()
