"""Мировая карта: авто-сетка слотов по зонам и рендер общей картинки.

Вместо ручных пиксельных слотов — ТРИ зоны-прямоугольника (в долях от размера
карты) и сетка внутри каждой. Слотов столько, сколько ячеек сетки → лимита на
число таверн больше нет, и код не зависит от точного размера картинки.

Слот-id зонно-блочный: north=10xx, green=20xx, red=30xx (xx — локальный индекс
1..cols*rows). Зона восстанавливается как slot//1000-1 → таверна всегда в своём
биоме. Старые слоты (1..15) гасятся разовой миграцией (base.py), переназначаются.

Спрайты зданий: assets/map_tavern_1..9.png. Уровень N → спрайт N (10 → 9).
"""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
MAP_FILE = ASSETS_DIR / "world.png"

# Порядок зон фиксирован (индекс → блок id). Совпадает с регионами игроков.
ZONE_ORDER = ["north_wilds", "green_valleys", "red_wastes"]

# Прямоугольник зоны в ДОЛЯХ (x1, y1, x2, y2) от ширины/высоты карты — суша
# биома, в стороне от моря, высоких пиков, рамки, легенды, компаса и подписей.
ZONE_RECTS: dict[str, tuple[float, float, float, float]] = {
    "north_wilds":   (0.05, 0.22, 0.37, 0.45),
    "green_valleys": (0.47, 0.22, 0.76, 0.71),
    "red_wastes":    (0.17, 0.61, 0.45, 0.89),
}
# Сетка (столбцы, строки) на зону. cols*rows = вместимость зоны.
ZONE_GRID: dict[str, tuple[int, int]] = {
    "north_wilds":   (6, 4),   # 24
    "green_valleys": (7, 7),   # 49
    "red_wastes":    (6, 5),   # 30
}

# Размер спрайта таверны = доля ширины ячейки (чтобы влезал и не наезжал).
SPRITE_CELL_FRAC = 0.92


def _zone_index(zone: str) -> int:
    return ZONE_ORDER.index(zone)


def zone_slots(zone: str) -> list[int]:
    """Все слот-id зоны (для assign_map_slot). id = (idx+1)*1000 + 1..cols*rows."""
    if zone not in ZONE_GRID:
        return []
    cols, rows = ZONE_GRID[zone]
    base = (_zone_index(zone) + 1) * 1000
    return [base + i for i in range(1, cols * rows + 1)]


def slot_zone(slot_id: int) -> str | None:
    idx = slot_id // 1000 - 1
    return ZONE_ORDER[idx] if 0 <= idx < len(ZONE_ORDER) else None


def _slot_cell_xy(slot_id: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    """Центр ячейки слота и её размер в пикселях: (cx, cy, cell_w, cell_h)."""
    zone = slot_zone(slot_id)
    if zone is None:
        return None
    cols, rows = ZONE_GRID[zone]
    local = slot_id % 1000 - 1
    if not 0 <= local < cols * rows:
        return None
    fx1, fy1, fx2, fy2 = ZONE_RECTS[zone]
    x1, y1, x2, y2 = fx1 * w, fy1 * h, fx2 * w, fy2 * h
    cw, ch = (x2 - x1) / cols, (y2 - y1) / rows
    col, row = local % cols, local // cols
    cx = x1 + cw * (col + 0.5)
    cy = y1 + ch * (row + 0.5)
    return int(cx), int(cy), int(cw), int(ch)


def sprite_tier(level: int) -> int:
    return min(max(level, 1), 9)


def _load_sprite(tier: int) -> Image.Image | None:
    p = ASSETS_DIR / f"map_tavern_{tier}.png"
    if not p.is_file():
        return None
    img = Image.open(p).convert("RGBA")
    solid = img.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    bbox = solid.getbbox()
    return img.crop(bbox) if bbox else img


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_label(d: ImageDraw.ImageDraw, x: int, y: int, text: str, size: int) -> None:
    """Подпись с тёмной обводкой по центру."""
    font = _font(size)
    if len(text) > 14:
        text = text[:13] + "…"
    bbox = d.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    px, py = x - w // 2, y
    for dx in (-2, -1, 1, 2):
        for dy in (-2, -1, 1, 2):
            d.text((px + dx, py + dy), text, font=font, fill=(35, 18, 5))
    d.text((px, py), text, font=font, fill=(250, 232, 185))


def _draw_fallback_marker(
    d: ImageDraw.ImageDraw, x: int, y: int, level: int, r: int
) -> None:
    """Маркер-щит с уровнем, если спрайтов нет."""
    d.ellipse([x - r, y - r, x + r, y + r], fill=(120, 60, 20),
              outline=(40, 20, 5), width=max(2, r // 9))
    font = _font(int(r * 1.1))
    text = str(level)
    bb = d.textbbox((0, 0), text, font=font)
    d.text((x - (bb[2] - bb[0]) // 2, y - (bb[3] - bb[1]) // 2 - bb[1]),
           text, font=font, fill=(250, 230, 180))


@dataclass
class MapTavern:
    slot: int
    level: int
    name: str


_cache_key: tuple | None = None
_cache_bytes: bytes | None = None


def render(taverns: list[MapTavern]) -> bytes:
    """Собирает карту с тавернами по авто-сетке. Кэширует по состоянию мира."""
    global _cache_key, _cache_bytes
    key = tuple(sorted((t.slot, t.level, t.name) for t in taverns))
    if key == _cache_key and _cache_bytes is not None:
        return _cache_bytes

    base = Image.open(MAP_FILE).convert("RGBA")
    w, h = base.size

    # Единый размер таверн = самая тесная ячейка среди зон (нигде не наедут).
    unit = min(
        min((fx2 - fx1) * w / ZONE_GRID[z][0], (fy2 - fy1) * h / ZONE_GRID[z][1])
        for z, (fx1, fy1, fx2, fy2) in ZONE_RECTS.items()
    )
    cell = int(unit)

    # 1) Позиции один раз.
    placed: list[tuple[int, int, MapTavern]] = []  # (cx, cy, tavern)
    for t in taverns:
        pos = _slot_cell_xy(t.slot, w, h)
        if pos is not None:
            placed.append((pos[0], pos[1], t))

    # 2) Подложки-«пятаки» под таверны — полупрозрачным слоем (читаемость на фоне).
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    rr = int(cell * 0.46)
    for cx, cy, _t in placed:
        od.ellipse([cx - rr, cy - int(rr * 0.7), cx + rr, cy + int(rr * 0.7)],
                   fill=(25, 15, 8, 95))
    base = Image.alpha_composite(base, overlay)
    d = ImageDraw.Draw(base)

    # 3) Спрайты + подписи. Рисуем сверху вниз, чтобы нижние перекрывали верхние.
    sprites: dict[int, Image.Image | None] = {}
    target_w = max(24, int(cell * SPRITE_CELL_FRAC))
    label_size = max(12, int(cell * 0.22))
    for cx, cy, t in sorted(placed, key=lambda p: p[1]):
        tier = sprite_tier(t.level)
        if tier not in sprites:
            sprites[tier] = _load_sprite(tier)
        sprite = sprites[tier]
        if sprite is not None:
            sp = sprite.resize(
                (target_w, max(1, int(sprite.height * target_w / sprite.width))),
                Image.Resampling.LANCZOS,
            )
            base.alpha_composite(sp, (cx - sp.width // 2, cy - int(sp.height * 0.72)))
        else:
            _draw_fallback_marker(d, cx, cy, t.level, target_w // 2)
        _draw_label(d, cx, cy + int(cell * 0.34), t.name, label_size)

    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    _cache_key, _cache_bytes = key, out.getvalue()
    return _cache_bytes
