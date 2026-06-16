"""Рендер складской ведомости: вписывает КОЛИЧЕСТВО в ячейки картинки
assets/tablica.png (5×3 = 15 ячеек). Названия ресурсов и иконки — уже на самой
картинке (впечатаны), код рисует только число под подписью.

Ячейка i (1..14) ← ресурс i из balance.RESOURCES (порядок совпадает с подписями
на картинке). 15-я ячейка — запасная (пустая). Кэш потокобезопасный (render
крутится в asyncio.to_thread, на складе бывает много игроков).
"""

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bot.game.balance import RESOURCES

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
BG_FILE = ASSETS_DIR / "tablica.png"
RESURS_DIR = ASSETS_DIR / "resurs"

# id ресурса -> файл иконки (assets/resurs/<name>.png, прозрачный фон). Нет файла —
# ячейка покажет только число (соль/рыба/молоко/камень — иконки в работе).
SPRITES = {
    "wood": "derevo", "grain": "zerno", "hops": "xmel", "water": "voda",
    "honey": "med", "berries": "yagodi", "game": "dich", "ore": "ruda",
    "clay": "glina", "herbs": "trava",
    "salt": "sol", "fish": "ryba", "milk": "moloko", "stone": "kamen",
}
_sprite_cache: dict[str, "Image.Image | None"] = {}


def _sprite(res: str) -> "Image.Image | None":
    """Иконка ресурса, обрезанная по непрозрачной области. Кэшируется."""
    if res in _sprite_cache:
        return _sprite_cache[res]
    name = SPRITES.get(res)
    p = RESURS_DIR / f"{name}.png" if name else None
    img = None
    if p and p.is_file():
        im = Image.open(p).convert("RGBA")
        bbox = im.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
        img = im.crop(bbox) if bbox else im
    _sprite_cache[res] = img
    return img


# Ячейки (x1, y1, x2, y2) на фоне 1024×1024 — нижняя половина каждой клетки
# (под впечатанной подписью), 5 столбцов × 3 строки.
CELLS = {
    1: (172, 372, 289, 470), 2: (313, 372, 430, 470), 3: (454, 372, 571, 470),
    4: (595, 372, 712, 470), 5: (736, 372, 853, 470),
    6: (172, 562, 289, 660), 7: (313, 562, 430, 660), 8: (454, 562, 571, 660),
    9: (595, 562, 712, 660), 10: (736, 562, 853, 660),
    11: (172, 752, 289, 850), 12: (313, 752, 430, 850), 13: (454, 752, 571, 850),
    14: (595, 752, 712, 850), 15: (736, 752, 853, 850),
}
# Ячеек хватает на все ресурсы — overflow в текст больше не нужен.
SHOWN_RESOURCES = RESOURCES[:len(CELLS)]
OVERFLOW_RESOURCES = RESOURCES[len(CELLS):]

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
    gap = 3
    for idx, res in enumerate(SHOWN_RESOURCES, 1):
        x1, y1, x2, y2 = CELLS[idx]
        cx, cy, w, h = (x1 + x2) // 2, (y1 + y2) // 2, x2 - x1, y2 - y1
        qty = str(int(inv.get(res, 0)))
        sprite = _sprite(res)
        if sprite is None:               # без иконки — число по центру ячейки
            qf = _fit_font(d, qty, w - 6, min(44, h - 4), 16, bold=True)
            l, t, r, b = d.textbbox((0, 0), qty, font=qf)
            d.text((cx - (r - l) / 2 - l, cy - (b - t) / 2 - t), qty, font=qf,
                   fill=QTY_COLOR)
            continue
        # иконка + число СТЕКОМ, центрируем группу целиком в ячейке
        qf = _fit_font(d, qty, w - 6, 30, 14, bold=True)
        l, t, r, b = d.textbbox((0, 0), qty, font=qf)
        num_w, num_h = r - l, b - t
        ih_max = h - num_h - gap - 4     # высота под иконку (остаток после числа)
        scale = min((w - 12) / sprite.width, ih_max / sprite.height)
        sp = sprite.resize(
            (max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))),
            Image.Resampling.LANCZOS)
        group_h = sp.height + gap + num_h
        gtop = y1 + (h - group_h) // 2
        base.alpha_composite(sp, (cx - sp.width // 2, gtop))
        d.text((cx - num_w / 2 - l, gtop + sp.height + gap - t), qty, font=qf,
               fill=QTY_COLOR)

    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    data = out.getvalue()
    with _cache_lock:
        _cache[key] = data
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return data
