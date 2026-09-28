"""Numeric application version and independently ordered build identity.

Prerelease ordering follows SemVer identifiers; numeric-only legacy versions keep
one-to-four components for compatibility. Build metadata does not affect precedence.
"""
import re
from pathlib import Path


def release_order(value: str) -> tuple:
    text = str(value).strip().removeprefix('v')
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+){0,3})(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?', text)
    if not match or len(text) > 200:
        raise ValueError('Invalid release identity.')
    nums = [int(x) for x in match[1].split('.')]
    if any(v > 65535 for v in nums):
        raise ValueError('Release component exceeds the native version range.')
    nums += [0] * (4 - len(nums))
    prerelease = []
    for item in (match[2] or '').split('.'):
        if not item:
            continue
        if item.isdigit():
            if len(item) > 1 and item[0] == '0':
                raise ValueError('Numeric prerelease identifiers cannot have leading zeros.')
            prerelease.append((0, int(item)))
        else:
            prerelease.append((1, item))
    return tuple(nums), int(not match[2]), tuple(prerelease)


def installed_release_id(version: str, root: Path | None = None) -> str:
    path = (root or Path(__file__).resolve().parents[1]) / 'RELEASE_ID.txt'
    identity = path.read_text(encoding='utf-8-sig').strip() if path.is_file() else version
    if release_order(identity)[0] != release_order(version)[0]:
        raise ValueError('Installed release identity and application version disagree.')
    return identity
