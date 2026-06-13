"""Рендер складской ведомости: вписывает ресурсы и их количество в ячейки
картинки assets/tablica.png (5×2 = 10 ячеек, по числу ресурсов Яруса 0).

Ячейка i (1..10) ← ресурс i из balance.RESOURCES. Кэш потокобезопасный
(render крутится в asyncio.to_thread, на складе бывает много игроков).
"""

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bot.game.balance import RESOURCE_NAMES, RESOURCES

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
BG_FILE = ASSETS_DIR / "tablica.png"

# Ячейки (x1, y1, x2, y2) на фоне 1024x1024 — сняты автодетектом по заливке.
CELLS = {
    1: (210, 402, 288, 513), 2: (336, 402, 423, 513), 3: (468, 402, 552, 513),
    4: (600, 402, 687, 513), 5: (738, 402, 812, 513),
    6: (210, 590, 288, 695), 7: (336, 590, 423, 695), 8: (468, 590, 552, 695),
    9: (600, 590, 687, 695), 10: (738, 590, 812, 695),
}

NAME_COLOR = (70, 40, 12)
QTY_COLOR = (120, 45, 18)

_CACHE_MAX = 32
_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_cache_lock = threading.Lock()


def background_exists() -> bool:
    return BG_FILE.is_file()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "DejaVuSans-Bold.ttf", "arialbd.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "DejaVuSans.ttf", "arial.ttf"]
    )
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_font(
    draw: ImageDraw.ImageDraw, text: str, max_w: int,
    start: int, min_size: int, bold: bool = False,
) -> ImageFont.FreeTypeFont:
    for size in range(start, min_size - 1, -1):
        f = _font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
    return _font(min_size, bold)


def render(inventory: dict | None) -> bytes:
    inv = inventory or {}
    key = tuple(sorted((r, int(inv.get(r, 0))) for r in RESOURCES))
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit

    base = Image.open(BG_FILE).convert("RGBA")
    d = ImageDraw.Draw(base)
    for idx, res in enumerate(RESOURCES, 1):
        x1, y1, x2, y2 = CELLS[idx]
        cx, w, h = (x1 + x2) // 2, x2 - x1, y2 - y1
        name = RESOURCE_NAMES[res]
        qty = str(int(inv.get(res, 0)))

        nf = _fit_font(d, name, w - 4, 22, 11)
        nw = d.textlength(name, font=nf)
        d.text((cx - nw / 2, y1 + h * 0.28), name, font=nf, fill=NAME_COLOR)

        qf = _fit_font(d, qty, w - 6, 42, 18, bold=True)
        qw = d.textlength(qty, font=qf)
        d.text((cx - qw / 2, y1 + h * 0.50), qty, font=qf, fill=QTY_COLOR)

    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    data = out.getvalue()
    with _cache_lock:
        _cache[key] = data
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return data
