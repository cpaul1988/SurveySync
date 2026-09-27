"""Contained static-file delivery shared by the desktop web shells."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

MEDIA_TYPES = {
    '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.ico': 'image/x-icon', '.css': 'text/css', '.js': 'text/javascript',
}


def serve_static(root: Path, name: str) -> FileResponse:
    if not name or '\\' in name or '\x00' in name:
        raise HTTPException(404)
    root = root.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower()),
                        headers={'Cache-Control': 'no-cache',
                                 'X-Content-Type-Options': 'nosniff'})
