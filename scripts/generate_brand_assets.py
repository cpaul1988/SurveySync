"""Build every SurveySync branding surface from the approved globe, not an S.

Run before ISCC and visual QA. The original artwork is never overwritten.
Only border-connected near-white background pixels become transparent;
interior gold lines and highlights are retained. No font files are bundled.
"""
from __future__ import annotations

import base64
from collections import deque
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
NAVY = (13, 31, 53)
CREAM = (247, 245, 240)
GOLD = (204, 173, 109)
SIZES = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]


def transparent_globe(source: Path) -> Image.Image:
    with Image.open(source) as original:
        image = original.convert('RGBA')
    pixels = image.load()
    width, height = image.size
    visited = set()
    queue = deque([(x, y) for x in range(width) for y in (0, height - 1)]
                  + [(x, y) for x in (0, width - 1) for y in range(height)])
    while queue:
        x, y = queue.popleft()
        if (x, y) in visited or not (0 <= x < width and 0 <= y < height):
            continue
        visited.add((x, y))
        r, g, b, a = pixels[x, y]
        if min(r, g, b) >= 211 and max(r, g, b) - min(r, g, b) <= 28:
            pixels[x, y] = (r, g, b, 0)
            queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    return image


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path('C:/Windows/Fonts') / ('segoeuib.ttf' if bold else 'segoeui.ttf'),
        Path('/usr/share/fonts/truetype/dejavu') /
        ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def wizard(globe: Image.Image, scale: int, small: bool = False) -> Image.Image:
    width, height = (55, 55) if small else (164, 314)
    canvas = Image.new('RGB', (width * scale, height * scale), NAVY)
    draw = ImageDraw.Draw(canvas)
    if small:
        mark = globe.resize((49 * scale, 49 * scale), Image.Resampling.LANCZOS)
        canvas.paste(mark, (3 * scale, 3 * scale), mark)
        return canvas
    draw.rectangle((0, 0, width * scale, 3 * scale), fill=GOLD)
    mark = globe.resize((132 * scale, 132 * scale), Image.Resampling.LANCZOS)
    canvas.paste(mark, (16 * scale, 37 * scale), mark)
    draw.text((82 * scale, 187 * scale), 'SurveySync', anchor='mm',
              font=font(20 * scale, True), fill=CREAM)
    draw.text((82 * scale, 214 * scale), 'UNIFYING GLOBAL DATA', anchor='mm',
              font=font(8 * scale, True), fill=GOLD)
    draw.line((24 * scale, 243 * scale, 140 * scale, 243 * scale), fill=GOLD,
              width=scale)
    draw.text((82 * scale, 263 * scale), 'One project.', anchor='mm',
              font=font(10 * scale), fill=CREAM)
    draw.text((82 * scale, 280 * scale), 'Every survey workflow.', anchor='mm',
              font=font(9 * scale), fill=CREAM)
    return canvas


def generate(root: Path = ROOT) -> list[Path]:
    source = root / 'branding/SurveySync_globe_512.png'
    globe = transparent_globe(source)
    outputs = []
    transparent = root / 'branding/SurveySync_globe_transparent_512.png'
    globe.save(transparent)
    outputs.append(transparent)
    payload = BytesIO()
    globe.save(payload, format='PNG')
    encoded = base64.b64encode(payload.getvalue()).decode('ascii')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
           'role="img" aria-label="SurveySync globe">'
           '<image width="512" height="512" href="data:image/png;base64,'
           + encoded + '"/></svg>\n')
    for relative in ('surveysync/static/surveysync_globe.svg',):
        path = root / relative
        path.write_text(svg, encoding='utf-8')
        outputs.append(path)
    for relative in ('branding/SurveySync.ico', 'surveysync/static/favicon.ico'):
        path = root / relative
        globe.save(path, format='ICO', sizes=SIZES)
        outputs.append(path)
    for scale, suffix in ((1, ''), (2, '_200'), (4, '_400')):
        for small, name in ((False, 'large'), (True, 'small')):
            path = root / f'installer/wizard_{name}{suffix}.bmp'
            wizard(globe, scale, small).save(path, format='BMP')
            outputs.append(path)
    return outputs


if __name__ == '__main__':
    for result in generate():
        print('Globe branding:', result.relative_to(ROOT))
