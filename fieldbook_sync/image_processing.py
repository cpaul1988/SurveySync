from __future__ import annotations
import logging

from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def _opencv_enhance(src: Path, dst: Path) -> bool:
    """Perspective-correct, deskew and enhance a photographed page when OpenCV exists.

    This is intentionally conservative: page-perspective correction is applied only when a
    large four-corner contour is found, and deskew is capped to small text-line angles.
    Returns False when OpenCV is unavailable or processing fails so Pillow can take over.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        # Page-level concurrency is managed by FieldBook Sync. Keep each OpenCV
        # page worker single-threaded to avoid N workers each spawning N more threads.
        try:
            cv2.setNumThreads(1)
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in image_processing; operation did not complete.", exc_info=True)
    except Exception:
        return False
    try:
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Detect an obvious photographed page boundary. Never crop merely because a random
        # four-sided object exists; the candidate must cover a large share of the frame.
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 45, 130)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        area_total = float(img.shape[0] * img.shape[1])
        page_quad = None
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
            if cv2.contourArea(contour) < area_total * 0.34:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) == 4:
                page_quad = approx.reshape(4, 2).astype('float32')
                break
        if page_quad is not None:
            sums = page_quad.sum(axis=1)
            diffs = np.diff(page_quad, axis=1).reshape(-1)
            rect = np.array([
                page_quad[np.argmin(sums)],  # top-left
                page_quad[np.argmin(diffs)], # top-right
                page_quad[np.argmax(sums)],  # bottom-right
                page_quad[np.argmax(diffs)], # bottom-left
            ], dtype='float32')
            tl, tr, br, bl = rect
            max_w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
            max_h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
            if max_w >= 400 and max_h >= 400:
                target = np.array([[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]], dtype='float32')
                matrix = cv2.getPerspectiveTransform(rect, target)
                img = cv2.warpPerspective(img, matrix, (max_w, max_h), borderValue=(255, 255, 255))
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Small deskew based on near-horizontal Hough line segments. Avoid large rotations
        # because notebook borders/pipe sketches can otherwise dominate the estimate.
        inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        lines = cv2.HoughLinesP(inv, 1, np.pi / 180, threshold=100,
                                minLineLength=max(80, img.shape[1] // 6), maxLineGap=18)
        angles = []
        if lines is not None:
            for line in lines[:250]:
                x1, y1, x2, y2 = line[0]
                angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
                while angle <= -90:
                    angle += 180
                while angle > 90:
                    angle -= 180
                if -12 <= angle <= 12:
                    angles.append(angle)
        if angles:
            angle = float(np.median(angles))
            if abs(angle) >= 0.35:
                h, w = img.shape[:2]
                center = (w / 2, h / 2)
                matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
                cos = abs(matrix[0, 0]); sin = abs(matrix[0, 1])
                new_w = int(h * sin + w * cos); new_h = int(h * cos + w * sin)
                matrix[0, 2] += new_w / 2 - center[0]
                matrix[1, 2] += new_h / 2 - center[1]
                img = cv2.warpAffine(img, matrix, (new_w, new_h), borderValue=(255, 255, 255))
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE lifts pencil/pen detail without a destructive hard threshold.
        clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        gray = cv2.GaussianBlur(gray, (0, 0), 0.6)
        sharp = cv2.addWeighted(gray, 1.55, gray, -0.55, 0)
        dst.parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(str(dst), sharp, [int(cv2.IMWRITE_JPEG_QUALITY), 94]))
    except Exception:
        return False


def enhance_fieldbook_image(src: str | Path, dst: str | Path) -> Path:
    """Create a high-legibility, analysis-ready derivative of a field-book page.

    When OpenCV is available this performs conservative page-boundary perspective correction,
    small-angle deskew, local contrast enhancement and sharpening. If OpenCV is unavailable it
    falls back to a Pillow-only EXIF/orientation + contrast/sharpen path. The original file is
    never modified. PaddleOCR-VL additionally performs its own orientation/unwarping internally.
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _opencv_enhance(src, dst):
        return dst
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        im = ImageOps.autocontrast(im, cutoff=0.5)
        im = ImageEnhance.Contrast(im).enhance(1.28)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=145, threshold=3))
        im = im.convert("RGB")
        im.save(dst, format="JPEG", quality=94, optimize=True)
    return dst


def normalized_bbox_to_pixels(bbox: Sequence[int] | None, width: int, height: int, padding: float = 0.08) -> tuple[int, int, int, int] | None:
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = [max(0, min(1000, int(v))) for v in bbox]
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    px1 = int(x1 / 1000 * width)
    py1 = int(y1 / 1000 * height)
    px2 = int(x2 / 1000 * width)
    py2 = int(y2 / 1000 * height)
    pad_x = max(20, int((px2 - px1) * padding))
    pad_y = max(20, int((py2 - py1) * padding))
    return max(0, px1 - pad_x), max(0, py1 - pad_y), min(width, px2 + pad_x), min(height, py2 + pad_y)


def crop_normalized_bbox(src: str | Path, bbox: Sequence[int] | None, dst: str | Path, padding: float = 0.18) -> Optional[Path]:
    if not bbox:
        return None
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        rect = normalized_bbox_to_pixels(bbox, im.width, im.height, padding=padding)
        if not rect:
            return None
        crop = im.crop(rect)
        max_dim = 2200
        if max(crop.size) > max_dim:
            scale = max_dim / max(crop.size)
            crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))))
        crop.save(dst, format="JPEG", quality=95, optimize=True)
    return dst


def ensure_enhanced_pages(pages: Iterable, enhanced_dir: Path) -> int:
    enhanced_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for page in pages:
        src = Path(page.image_path)
        dst = enhanced_dir / f"{page.page_id}_enhanced.jpg"
        try:
            enhance_fieldbook_image(src, dst)
            page.enhanced_image_path = str(dst)
            count += 1
        except Exception:
            page.enhanced_image_path = None
    return count


def ensure_enhanced_pages_parallel(
    pages: Iterable,
    enhanced_dir: Path,
    *,
    max_workers: int = 1,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    """Enhance independent pages concurrently with bounded worker fan-out.

    OpenCV/Pillow page enhancement is naturally page-parallel. v8.0.7 uses a
    bounded thread pool so native OpenCV work can occupy multiple CPU cores while
    avoiding the much larger memory cost of multiple PaddleOCR model processes.
    """
    page_list = list(pages)
    total = len(page_list)
    if not total:
        return 0
    enhanced_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(int(max_workers or 1), total))

    def work(page):
        if cancel_check and cancel_check():
            return page, None
        src = Path(page.image_path)
        dst = enhanced_dir / f"{page.page_id}_enhanced.jpg"
        try:
            enhance_fieldbook_image(src, dst)
            return page, str(dst)
        except Exception:
            return page, None

    completed = 0
    success = 0
    if workers == 1:
        for page in page_list:
            if cancel_check and cancel_check():
                break
            page, out = work(page)
            page.enhanced_image_path = out
            success += int(bool(out))
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
        return success

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="FBS-enhance") as pool:
        future_map = {pool.submit(work, page): page for page in page_list}
        for future in as_completed(future_map):
            if cancel_check and cancel_check():
                for pending in future_map:
                    pending.cancel()
                break
            page, out = future.result()
            page.enhanced_image_path = out
            success += int(bool(out))
            completed += 1
            if progress_callback:
                progress_callback(completed, total)
    return success
