"""Resource payload and link-compatibility regressions; no PE file is executed."""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from res_to_coff import Resource, parse_res, to_coff


def record(kind=0, name=0, language=0, data=b''):
    return struct.pack('<IIHHHHIHHII', len(data), 32, 65535, kind, 65535, name, 0, 0, language, 0, 0) + data + bytes((-len(data)) % 4)


def sample():
    return record() + record(24, 1, 1033, b'<assembly>asInvoker</assembly>') + record(16, 1, 1033, b'version')


def unpack_object(raw):
    machine, count, _, symbols, nsyms, optional, _ = struct.unpack_from('<HHIIIHH', raw)
    assert (machine, count, nsyms, optional) == (0x8664, 1, 2, 0)
    hdr = struct.unpack_from('<8sIIIIIIHHI', raw, 20)
    name, _, _, size, ptr, relptr, _, nrel, _, flags = hdr
    assert name.rstrip(b'\x00') == b'.rsrc'
    assert flags & 0x20000000 == 0  # not executable
    assert flags & 0x80000000 == 0  # not writable
    assert struct.unpack_from('<8sIhHBB', raw, symbols)[2:] == (1, 0, 3, 1)
    relocs = [struct.unpack_from('<IIH', raw, relptr + 10 * i) for i in range(nrel)]
    assert all(index == 0 and kind == 3 for _, index, kind in relocs)
    return raw[ptr:ptr + size], relocs


def read_tree(section, base=0, key=()):
    _, _, _, _, named, count = struct.unpack_from('<IIHHHH', section, base)
    assert named == 0
    result = {}
    for i in range(count):
        name, target = struct.unpack_from('<II', section, base + 16 + 8 * i)
        if target & 0x80000000:
            result.update(read_tree(section, target & 0x7fffffff, key + (name,)))
        else:
            address, size, codepage, reserved = struct.unpack_from('<IIII', section, target)
            assert codepage == reserved == 0
            assert address + size <= len(section)
            result[key + (name,)] = section[address:address + size]
    return result


def test_all_resource_payloads_and_languages_survive():
    raw = sample() + record(3, 2, 1033, b'ICON') + record(14, 1, 1033, b'GROUP') + record(16, 1, 1031, b'german')
    resources = parse_res(raw)
    section, relocs = unpack_object(to_coff(resources))
    assert len(relocs) == len(resources) == 5
    assert read_tree(section) == {(r.kind, r.name, r.language): r.data for r in resources}


def test_deterministic():
    resources = parse_res(sample())
    assert to_coff(resources) == to_coff(list(reversed(resources)))


@pytest.mark.parametrize('raw', [b'', b'x' * 31, record(), sample()[:-1], sample() + b'x', record(3, 1, 1033, b'icon'), record() + record(10, 1, 1033, b'x'), record() + record(3, 0, 1033, b'x'), record() + record(3, 1, 1033), sample() + record(16, 1, 1033, b'duplicate')])
def test_reject_invalid_res(raw):
    with pytest.raises(ValueError):
        parse_res(raw)


def test_reject_named_resource():
    raw = bytearray(sample())
    struct.pack_into('<H', raw, 40, ord('A'))
    with pytest.raises(ValueError, match='numeric'):
        parse_res(bytes(raw))


def test_reject_nonzero_padding():
    raw = bytearray(record() + record(3, 1, 1033, b'x'))
    raw[-1] = 1
    with pytest.raises(ValueError, match='padding'):
        parse_res(bytes(raw))


def test_reject_nonzero_version():
    raw = bytearray(sample())
    struct.pack_into('<I', raw, 48, 1)
    with pytest.raises(ValueError, match='metadata'):
        parse_res(bytes(raw))


@pytest.mark.parametrize('resources', [[], [Resource(3, 1, 1033, b'x')] * 2, [Resource(3, 1, 70000, b'x')], [Resource(10, 1, 1033, b'x')]])
def test_reject_invalid_object_inputs(resources):
    with pytest.raises(ValueError):
        to_coff(resources)


def test_go_links_metadata_without_executing_binary(tmp_path):
    go = shutil.which('go')
    if not go:
        pytest.skip('Go toolchain unavailable for cross-link check')
    (tmp_path / 'main.go').write_text('package main\nfunc main() {}\n')
    (tmp_path / 'resource_windows_amd64.syso').write_bytes(to_coff(parse_res(sample())))
    env = dict(os.environ, GOOS='windows', GOARCH='amd64', CGO_ENABLED='0', GO111MODULE='off', GOPROXY='off', GOTOOLCHAIN='local')
    subprocess.run([go, 'build', '-trimpath', '-ldflags=-H=windowsgui', '-o', 'test.exe', '.'], cwd=tmp_path, env=env, check=True, capture_output=True, timeout=120)
    raw = (tmp_path / 'test.exe').read_bytes()
    assert raw[:2] == b'MZ'
    pe = struct.unpack_from('<I', raw, 0x3c)[0]
    count = struct.unpack_from('<H', raw, pe + 6)[0]
    optional_size = struct.unpack_from('<H', raw, pe + 20)[0]
    section_start = pe + 24 + optional_size
    for i in range(count):
        name, _, virtual, size, ptr = struct.unpack_from('<8sIIII', raw, section_start + i * 40)
        if name.rstrip(b'\x00') == b'.rsrc':
            data = bytearray(raw[ptr:ptr + size])
            # Only leaf pointers are RVAs after linking; convert for read_tree.
            def relativize(offset):
                count = struct.unpack_from('<H', data, offset + 14)[0]
                for j in range(count):
                    _, target = struct.unpack_from('<II', data, offset + 16 + j * 8)
                    if target & 0x80000000:
                        relativize(target & 0x7fffffff)
                    else:
                        addr = struct.unpack_from('<I', data, target)[0]
                        struct.pack_into('<I', data, target, addr - virtual)
            relativize(0)
            assert read_tree(data) == {(r.kind, r.name, r.language): r.data for r in parse_res(sample())}
            break
    else:
        pytest.fail('Linked PE is missing .rsrc')
