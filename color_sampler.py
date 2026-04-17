"""
color_sampler.py
Pixel-level color analysis from a CGImage screenshot.
macOS-only (uses Quartz raw bytes). On other platforms, annotate_colors()
is a no-op and OCRBlocks keep their default colors (#ffffff / #000000).
"""

import sys
from collections import Counter

from ocr_model import OCRBlock


def annotate_colors(
    cg_image,
    blocks: list[OCRBlock],
    logical_w: float,
    logical_h: float,
) -> None:
    """
    Sample text_color and bg_color for each block from the CGImage.
    Mutates blocks in-place. Safe to call with an empty list.

    Uses CGDataProviderCopyData for raw byte access — ~1000× faster than
    NSBitmapImageRep.colorAtX_y_() which allocates an NSColor per pixel.

    On non-macOS platforms this is a silent no-op; blocks keep their defaults.
    """
    if sys.platform != "darwin" or not blocks or cg_image is None:
        return

    try:
        import Quartz
        dp      = Quartz.CGImageGetDataProvider(cg_image)
        cf_data = Quartz.CGDataProviderCopyData(dp)
        raw     = bytes(cf_data)
        img_w   = Quartz.CGImageGetWidth(cg_image)
        img_h   = Quartz.CGImageGetHeight(cg_image)
        bpr     = Quartz.CGImageGetBytesPerRow(cg_image)
        bpp     = Quartz.CGImageGetBitsPerPixel(cg_image) // 8
        # kCGBitmapByteOrder32Little (0x2000) → BGRA byte order on Apple Silicon
        is_bgra = bool(Quartz.CGImageGetBitmapInfo(cg_image) & 0x2000)
    except Exception as e:
        print(f"[ColorSampler] 無法讀取 CGImage 像素: {e}")
        return

    for block in blocks:
        try:
            tc, bc = _sample_block(raw, bpr, bpp, is_bgra,
                                   block.bbox, logical_w, logical_h, img_w, img_h)
            block.text_color = tc
            block.bg_color   = bc
        except Exception:
            pass   # keep defaults on any per-block failure


def _sample_block(
    raw: bytes,
    bpr: int,
    bpp: int,
    is_bgra: bool,
    bbox: tuple[float, float, float, float],
    logical_w: float,
    logical_h: float,
    img_w: int,
    img_h: int,
) -> tuple[str, str]:
    """
    Return (text_hex, bg_hex) for one bbox.

    Background color  — 5-bit-quantized mode of sampled pixels, then averaged
                        with nearby pixels for precision.
    Text color        — pixels with color distance > 40 from background,
                        top-third by distance, averaged.
    """
    sx = img_w / max(logical_w, 1)   # logical → physical (Retina) scale
    sy = img_h / max(logical_h, 1)
    bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])

    if bw < 4 or bh < 4:
        return "#ffffff", "#000000"

    def get_rgb(lx: int, ly: int) -> tuple[int, int, int]:
        px = max(0, min(img_w - 1, round(lx * sx)))
        py = max(0, min(img_h - 1, round(ly * sy)))
        o  = py * bpr + px * bpp
        if is_bgra:
            return (raw[o + 2], raw[o + 1], raw[o])
        return     (raw[o],     raw[o + 1], raw[o + 2])

    # Uniform sub-sample inside the bbox
    step   = max(3, min(bw, bh) // 8)
    pixels = []
    for y in range(by, by + bh, step):
        for x in range(bx, bx + bw, step):
            try:
                pixels.append(get_rgb(x, y))
            except IndexError:
                pass

    if not pixels:
        return "#ffffff", "#000000"

    # Background: take mode of raw pixel colors, average close neighbors
    bg_q  = Counter(pixels).most_common(1)[0][0]
    close = [p for p in pixels if sum(abs(a - b) for a, b in zip(p, bg_q)) < 20]
    bg    = (tuple(sum(p[i] for p in close) // len(close) for i in range(3))
             if len(close) > 2 else bg_q)

    # Text color: high-distance pixels, top third by distance
    def dist(c: tuple) -> int:
        return sum(abs(a - b) for a, b in zip(c, bg))

    fg = [p for p in pixels if dist(p) > 40]
    if fg:
        fg.sort(key=dist, reverse=True)
        top  = fg[:max(1, len(fg) // 3)]
        text = tuple(sum(p[i] for p in top) // len(top) for i in range(3))
    else:
        lum  = bg[0] * 0.299 + bg[1] * 0.587 + bg[2] * 0.114
        text = (255, 255, 255) if lum < 128 else (0, 0, 0)

    def to_hex(rgb: tuple) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    return to_hex(text), to_hex(bg)
