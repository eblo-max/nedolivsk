"""Экран персонажа: кукла с экипировкой.

Фон: assets/character.png (1024x1024).
Предметы: assets/items/<item_id>.png — вписываются в рамку своего слота.
Если фона нет — хендлер покажет текстовый экран.
"""

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
BG_FILE = ASSETS_DIR / "character.png"
ITEMS_DIR = ASSETS_DIR / "items"

# Слот -> рамка (x1, y1, x2, y2) на фоне 1024x1024.
# Координаты сняты автодетектом по внутреннему краю деревянных рамок.
SLOT_BOXES = {
    "head": (138, 141, 254, 256),
    "left_hand": (137, 325, 254, 439),
    "belt": (137, 558, 254, 666),
    "legs": (137, 746, 254, 861),
    "chest": (454, 319, 570, 432),
    "amulet": (626, 141, 742, 256),
    "talisman": (754, 141, 881, 256),
    "right_hand": (771, 325, 876, 439),
    "weapon": (770, 558, 876, 666),
    "bag": (770, 746, 880, 861),
    "boots": (390, 720, 615, 875),  # прямо на ногах силуэта, без рамки
}

# Потокобезопасный LRU: render крутится в asyncio.to_thread, а в группе
# рендерят сразу много игроков с разной экипировкой.
_CACHE_MAX = 64
_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_cache_lock = threading.Lock()


def background_exists() -> bool:
    return BG_FILE.is_file()


def _item_sprite(sprite_name: str) -> Image.Image | None:
    p = ITEMS_DIR / f"{sprite_name}.png"
    if not p.is_file():
        return None
    img = Image.open(p).convert("RGBA")
    solid = img.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    bbox = solid.getbbox()
    return img.crop(bbox) if bbox else img


def render(equipment: dict | None) -> bytes:
    """Кукла с надетыми вещами. Кэш по составу экипировки."""
    equipment = equipment or {}
    key = tuple(sorted(equipment.items()))
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit

    from bot.game.items import CATALOG, parse_entry

    TIER_FRAME = {2: (170, 175, 190, 255), 3: (212, 168, 50, 255)}  # серебро/золото

    base = Image.open(BG_FILE).convert("RGBA")
    draw = ImageDraw.Draw(base)
    for slot, entry in equipment.items():
        box = SLOT_BOXES.get(slot)
        if box is None:
            continue
        item_id, tier = parse_entry(entry)
        item = CATALOG.get(item_id)
        sprite_name = (item.sprite or item_id) if item else item_id
        sprite = _item_sprite(sprite_name)
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
    data = out.getvalue()
    with _cache_lock:
        _cache[key] = data
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return data
