from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import List

import pymupdf as fitz

from .models import FieldBookPage


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PDF_EXTS = {".pdf"}


def _page_id(source_name: str, content_hash: str, page_number: int) -> str:
    raw = f"{source_name}|{content_hash}|{page_number}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:12]


def clear_fieldbook_workspace(page_dir: Path) -> None:
    if page_dir.exists():
        shutil.rmtree(page_dir)
    page_dir.mkdir(parents=True, exist_ok=True)


def ingest_fieldbook_path(path: Path, filename: str, page_dir: Path, dpi: int = 170) -> List[FieldBookPage]:
    """Ingest a PDF or image from disk without buffering the whole source file in RAM."""
    path = Path(path)
    page_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(filename).stem)[:80] or "fieldbook"
    pages: List[FieldBookPage] = []
    content_hash = _sha1_file(path)

    if suffix in PDF_EXTS:
        doc = fitz.open(str(path))
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        try:
            for idx in range(doc.page_count):
                page = doc.load_page(idx)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                page_num = idx + 1
                page_id = _page_id(filename, content_hash, page_num)
                out = page_dir / f"{safe_stem}_p{page_num:04d}_{page_id}.jpg"
                pix.save(str(out), output="jpg", jpg_quality=88)
                pages.append(FieldBookPage(
                    page_id=page_id,
                    source_name=filename,
                    page_number=page_num,
                    image_path=str(out),
                    mime_type="image/jpeg",
                ))
        finally:
            doc.close()
        return pages

    if suffix in IMAGE_EXTS:
        page_num = 1
        page_id = _page_id(filename, content_hash, page_num)
        out = page_dir / f"{safe_stem}_p0001_{page_id}{suffix}"
        shutil.copy2(path, out)
        mime = mimetypes.guess_type(out.name)[0] or "image/jpeg"
        pages.append(FieldBookPage(
            page_id=page_id,
            source_name=filename,
            page_number=1,
            image_path=str(out),
            mime_type=mime,
        ))
        return pages

    raise ValueError("Field book must be a PDF, PNG, JPG/JPEG, or WEBP file.")


def ingest_fieldbook_file(raw: bytes, filename: str, page_dir: Path, dpi: int = 170) -> List[FieldBookPage]:
    """Backward-compatible byte-oriented helper retained for tests and small internal callers."""
    page_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(filename).stem)[:80] or "fieldbook"
    pages: List[FieldBookPage] = []
    content_hash = hashlib.sha1(raw).hexdigest()[:12]

    if suffix in PDF_EXTS:
        doc = fitz.open(stream=raw, filetype="pdf")
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        try:
            for idx in range(doc.page_count):
                page = doc.load_page(idx)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                page_num = idx + 1
                page_id = _page_id(filename, content_hash, page_num)
                out = page_dir / f"{safe_stem}_p{page_num:04d}_{page_id}.jpg"
                pix.save(str(out), output="jpg", jpg_quality=88)
                pages.append(FieldBookPage(
                    page_id=page_id,
                    source_name=filename,
                    page_number=page_num,
                    image_path=str(out),
                    mime_type="image/jpeg",
                ))
        finally:
            doc.close()
        return pages

    if suffix in IMAGE_EXTS:
        page_num = 1
        page_id = _page_id(filename, content_hash, page_num)
        out = page_dir / f"{safe_stem}_p0001_{page_id}{suffix}"
        out.write_bytes(raw)
        mime = mimetypes.guess_type(out.name)[0] or "image/jpeg"
        pages.append(FieldBookPage(
            page_id=page_id,
            source_name=filename,
            page_number=1,
            image_path=str(out),
            mime_type=mime,
        ))
        return pages

    raise ValueError("Field book must be a PDF, PNG, JPG/JPEG, or WEBP file.")
