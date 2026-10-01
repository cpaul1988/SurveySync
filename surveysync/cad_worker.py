"""Disposable DXF parsing/QA worker: bounded output and parent-enforced timeout."""

import json
import sys
from pathlib import Path
from .cad_geometry import read_drawing, analyze


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        data = read_drawing(request["file"], request["drawing_units"], request["project_units"])
        data["qa"] = analyze(data, request["gap_search_ft"])
        result = {"ok": True, "drawing": data}
    except Exception as exc:
        # Process boundary: translate parser/native library failures without accepting partial geometry.
        result = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:1000]}
    Path(sys.argv[2]).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
