"""Мировая карта: слоты для таверн и рендер общей картинки.

Спрайты зданий: assets/map_tavern_1..9.png (прозрачный фон).
Уровень таверны N -> спрайт N, уровень 10 -> спрайт 9 (самый роскошный).
Если спрайта нет — рисуется простой маркер с номером уровня.
"""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
MAP_FILE = ASSETS_DIR / "worldmap.jpeg"

# Слоты: id -> (x, y центра круга, зона)
SLOTS: dict[int, tuple[int, int, str]] = {
    1: (612, 392, "north_wilds"),
    2: (815, 315, "north_wilds"),
    3: (955, 468, "north_wilds"),
    4: (1535, 290, "green_valleys"),
    5: (1915, 302, "green_valleys"),
    6: (2098, 232, "green_valleys"),
    7: (1755, 518, "green_valleys"),
    8: (2055, 478, "green_valleys"),
    9: (1905, 635, "green_valleys"),
    10: (500, 612, "red_wastes"),
    11: (742, 722, "red_wastes"),
    12: (1010, 782, "red_wastes"),
    13: (1282, 662, "red_wastes"),
    14: (468, 855, "red_wastes"),
    15: (1192, 545, "red_wastes"),
}

def sprite_width(tier: int) -> int:
    """Хибарка меньше, дворец больше: 145..225 px."""
    return 135 + tier * 10


def zone_slots(zone: str) -> list[int]:
    return [sid for sid, (_, _, z) in SLOTS.items() if z == zone]


def sprite_tier(level: int) -> int:
    return min(max(level, 1), 9)


def _load_sprite(tier: int) -> Image.Image | None:
    p = ASSETS_DIR / f"map_tavern_{tier}.png"
    if not p.is_file():
        return None
    img = Image.open(p).convert("RGBA")
    # обрезаем пустые поля по порогу альфы (игнорируем полупрозрачный мусор)
    solid = img.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    bbox = solid.getbbox()
    if bbox:
        img = img.crop(bbox)
    return img


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_label(d: ImageDraw.ImageDraw, x: int, y: int, text: str) -> None:
    """Подпись с тёмной обводкой, по центру."""
    font = _font(30)
    if len(text) > 16:
        text = text[:15] + "…"
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    px, py = x - w // 2, y
    for dx in (-2, 0, 2):
        for dy in (-2, 0, 2):
            d.text((px + dx, py + dy), text, font=font, fill=(40, 20, 5))
    d.text((px, py), text, font=font, fill=(250, 230, 180))


def _draw_fallback_marker(
    img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, level: int
) -> None:
    """Маркер-щит с уровнем, если спрайтов ещё нет."""
    r = 46
    d.ellipse([x - r, y - r, x + r, y + r], fill=(120, 60, 20), outline=(40, 20, 5), width=5)
    font = _font(44)
    text = str(level)
    bbox = d.textbbox((0, 0), text, font=font)
    d.text(
        (x - (bbox[2] - bbox[0]) // 2, y - (bbox[3] - bbox[1]) // 2 - 8),
        text, font=font, fill=(250, 230, 180),
    )


@dataclass
class MapTavern:
    slot: int
    level: int
    name: str


_cache_key: tuple | None = None
_cache_bytes: bytes | None = None


def render(taverns: list[MapTavern]) -> bytes:
    """Собирает карту с таврернами. Кэширует по состоянию мира."""
    global _cache_key, _cache_bytes
    key = tuple(sorted((t.slot, t.level, t.name) for t in taverns))
    if key == _cache_key and _cache_bytes is not None:
        return _cache_bytes

    base = Image.open(MAP_FILE).convert("RGBA")
    d = ImageDraw.Draw(base)
    sprites: dict[int, Image.Image | None] = {}

    for t in sorted(taverns, key=lambda t: SLOTS[t.slot][1]):  # сверху вниз
        x, y, _zone = SLOTS[t.slot]
        tier = sprite_tier(t.level)
        if tier not in sprites:
            sprites[tier] = _load_sprite(tier)
        sprite = sprites[tier]
        if sprite is not None:
            width = sprite_width(tier)
            sp = sprite.resize(
                (width, int(sprite.height * width / sprite.width)), Image.Resampling.LANCZOS
            )
            # низ здания — в центр круга, чуть ниже
            base.alpha_composite(sp, (x - sp.width // 2, y - sp.height + 55))
        else:
            _draw_fallback_marker(base, d, x, y, t.level)
        _draw_label(d, x, y + 62, t.name)

    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    _cache_key, _cache_bytes = key, out.getvalue()
    return _cache_bytes
