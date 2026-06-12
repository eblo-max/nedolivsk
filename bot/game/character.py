"""Экран персонажа: кукла с экипировкой.

Фон: assets/character.png (1024x1024).
Предметы: assets/items/<item_id>.png — вписываются в рамку своего слота.
Если фона нет — хендлер покажет текстовый экран.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
BG_FILE = ASSETS_DIR / "character.png"
ITEMS_DIR = ASSETS_DIR / "items"

# Слот -> рамка (x1, y1, x2, y2) на фоне 1024x1024
SLOT_BOXES = {
    "head": (133, 142, 255, 263),
    "left_hand": (133, 320, 255, 442),
    "belt": (133, 543, 252, 662),
    "legs": (128, 752, 250, 870),
    "chest": (455, 315, 577, 442),
    "amulet": (623, 142, 744, 262),
    "talisman": (758, 142, 880, 262),
    "right_hand": (760, 318, 882, 440),
    "weapon": (760, 543, 882, 662),
    "bag": (760, 752, 882, 870),
    "boots": (390, 720, 615, 875),  # прямо на ногах силуэта
}

_cache_key: tuple | None = None
_cache_bytes: bytes | None = None


def background_exists() -> bool:
    return BG_FILE.is_file()


def _item_sprite(item_id: str) -> Image.Image | None:
    p = ITEMS_DIR / f"{item_id}.png"
    if not p.is_file():
        return None
    img = Image.open(p).convert("RGBA")
    solid = img.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    bbox = solid.getbbox()
    return img.crop(bbox) if bbox else img


def render(equipment: dict | None) -> bytes:
    """Кукла с надетыми вещами. Кэш по составу экипировки."""
    global _cache_key, _cache_bytes
    equipment = equipment or {}
    key = tuple(sorted(equipment.items()))
    if key == _cache_key and _cache_bytes is not None:
        return _cache_bytes

    from bot.game.items import parse_entry

    TIER_FRAME = {2: (170, 175, 190, 255), 3: (212, 168, 50, 255)}  # серебро/золото

    base = Image.open(BG_FILE).convert("RGBA")
    draw = ImageDraw.Draw(base)
    for slot, entry in equipment.items():
        box = SLOT_BOXES.get(slot)
        if box is None:
            continue
        item_id, tier = parse_entry(entry)
        sprite = _item_sprite(item_id)
        if sprite is None:
            continue
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        scale = min(bw / sprite.width, bh / sprite.height)
        sp = sprite.resize(
            (max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))),
            Image.LANCZOS,
        )
        px = x1 + (bw - sp.width) // 2
        py = y1 + (bh - sp.height) // 2
        base.alpha_composite(sp, (px, py))
        if tier in TIER_FRAME and slot != "boots":  # у сапог нет рамки на фоне
            draw.rounded_rectangle(
                [x1 - 4, y1 - 4, x2 + 4, y2 + 4],
                radius=10, outline=TIER_FRAME[tier], width=6,
            )

    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    _cache_key, _cache_bytes = key, out.getvalue()
    return _cache_bytes
