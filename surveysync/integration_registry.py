"""Read-only capability inventory. Installed packages do not enable planned adapters.

Probes read distribution metadata only: no optional imports, executable launches,
network requests, or license activation happen during application startup.
"""

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Callable


@dataclass(frozen=True)
class Adapter:
    key: str
    label: str
    package: str | None
    license: str
    implemented: bool
    capabilities: tuple[str, ...]
    note: str


ADAPTERS = (
    Adapter(
        "proj",
        "PROJ / pyproj",
        "pyproj",
        "MIT",
        True,
        ("CRS transformations", "operation diagnostics"),
        "Requires installed grids for some operations.",
    ),
    Adapter(
        "dxf_builtin",
        "SurveySync DXF",
        None,
        "SurveySync project license",
        True,
        ("basic ASCII DXF points and linework",),
        "Limited entity support; expanded ezdxf adapter is planned.",
    ),
    Adapter(
        "las_builtin",
        "Native LAS metadata",
        None,
        "SurveySync project license",
        True,
        ("LAS header inspection",),
        "Available without optional decoders.",
    ),
    Adapter(
        "las",
        "laspy sampling",
        "laspy",
        "BSD-2-Clause",
        True,
        ("optional LAS sampling",),
        "LAZ decoding additionally requires a supported compression backend.",
    ),
    Adapter(
        "ezdxf",
        "ezdxf CAD",
        "ezdxf",
        "MIT",
        False,
        (),
        "Planned: richer DXF entities and conversion reports.",
    ),
    Adapter(
        "shapely",
        "Shapely geometry QA",
        "shapely",
        "BSD-3-Clause; GEOS LGPL-2.1",
        False,
        (),
        "Planned: geometry checks and explicit correction previews.",
    ),
    Adapter(
        "rtklib",
        "RTKLIB GNSS",
        None,
        "BSD-2-Clause",
        False,
        (),
        "Planned: external processing adapter; executable availability is not probed.",
    ),
    Adapter(
        "geocompy",
        "GeoComPy instruments",
        "GeoComPy",
        "MIT",
        False,
        (),
        "Planned: explicitly connected Leica instruments; no device discovery.",
    ),
)


def inventory(probe: Callable[[str], str] = version) -> dict:
    records = []
    for adapter in ADAPTERS:
        installed = None
        error = None
        if adapter.package:
            try:
                installed = probe(adapter.package)
            except PackageNotFoundError:
                installed = None
            except (OSError, ValueError) as exc:
                error = f"Package metadata unavailable: {exc}"
        status = "planned"
        if adapter.implemented:
            status = "ready" if adapter.package is None or installed else "unavailable"
        records.append(
            {
                "key": adapter.key,
                "label": adapter.label,
                "package": adapter.package,
                "version": installed,
                "license": adapter.license,
                "status": status,
                "capabilities": list(adapter.capabilities) if status == "ready" else [],
                "note": adapter.note,
                "error": error,
            }
        )
    return {
        "schema": 1,
        "adapters": records,
        "notice": "Inventory does not activate adapters or certify licensing. See THIRD_PARTY_NOTICES.md.",
    }
