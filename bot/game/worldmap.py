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
import json
import math
import random
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
# Минимальная дистанция между тавернами (доля от стороны карты) — blue-noise:
# таверны раскиданы органично, но не ближе этого, чтобы спрайты и подписи дышали.
MIN_DIST = 0.072
# Размер спрайта таверны = доля от MIN_DIST·сторона (чтобы влезал и не наезжал).
SPRITE_FRAC = 0.62

# 25 «континентов» карты — именованные локации. Порядок совпадает с world25_slots.json:
# первые 5 — снег (north_wilds), 14 — зелень (green_valleys), 6 — пустыня (red_wastes).
# Таверна садится в континент СВОЕЙ зоны (player.region), а не по id%25 — так карта и
# меню визуально соответствуют реальной серверной зоне. Единый источник имён.
CONTINENT_NAMES = [
    "Холодненькое", "Трясучий Кряж", "Рассольные Фьорды", "Белая Горячка", "Опохмельный Зарубеж",
    "Зелёный Змий", "Хмельное Раздолье", "Дубовый Край", "Пивные Реки", "Изумрудная Чарка",
    "Бражные Поля", "Огуречная Лощина", "Светлое Разливное", "Чекушкины Холмы", "Тихий Перепой",
    "Вискарный Дол", "Заливные-за-Воротник", "Старый Запой", "Настоечный Простор",
    "Сушняковые Земли", "Краснорожие Пустоши", "Рассольник", "Сушняк-Предел", "Похмельные Дюны", "Сухой Закон",
]

# Биом континента → игровая зона (player.region).
BIOME_ZONE = {"snow": "north_wilds", "green": "green_valleys",
              "desert": "red_wastes", "red": "red_wastes"}

_CONTS_CACHE: list[dict] | None = None
_ZONE_CONTS_CACHE: dict[str, list[dict]] | None = None


def continents() -> list[dict]:
    """25 континентов: индекс, центр (норм. x/y), биом, ИМЯ. Кэш из world25_slots.json."""
    global _CONTS_CACHE
    if _CONTS_CACHE is None:
        p = MAP_FILE.parent / "world25_slots.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:   # noqa: BLE001
            data = []
        _CONTS_CACHE = [
            {"i": i, "x": c[1], "y": c[2], "biome": c[3] if len(c) > 3 else "",
             "name": CONTINENT_NAMES[i] if i < len(CONTINENT_NAMES) else f"Земля {c[0]}"}
            for i, c in enumerate(data)
        ]
    return _CONTS_CACHE


def zone_continents(region: str) -> list[dict]:
    """Континенты биома зоны игрока (для размещения таверны в её реальной зоне)."""
    global _ZONE_CONTS_CACHE
    if _ZONE_CONTS_CACHE is None:
        m: dict[str, list[dict]] = {z: [] for z in ZONE_ORDER}
        for c in continents():
            z = BIOME_ZONE.get(c["biome"])
            if z in m:
                m[z].append(c)
        _ZONE_CONTS_CACHE = m
    return (_ZONE_CONTS_CACHE.get(region)
            or _ZONE_CONTS_CACHE.get("green_valleys") or [])


def continent_for(region: str, player_id: int) -> dict | None:
    """Континент таверны — один из континентов её зоны, стабильно по id игрока."""
    cs = zone_continents(region or "green_valleys")
    return cs[player_id % len(cs)] if cs else None


def continent_name(region: str, player_id: int) -> str:
    """Имя локации таверны = континент её ЗОНЫ (совпадает с раскладкой карты мира)."""
    c = continent_for(region, player_id)
    return c["name"] if c else CONTINENT_NAMES[player_id % len(CONTINENT_NAMES)]


def _zone_index(zone: str) -> int:
    return ZONE_ORDER.index(zone)


def _poisson(rect: tuple[float, float, float, float], d: float,
             seed: int, k: int = 30) -> list[tuple[float, float]]:
    """Blue-noise точки в прямоугольнике (Бридсон): минимум d между точками.
    Детерминированно по seed → таверна на слоте всегда в одном месте."""
    x1, y1, x2, y2 = rect
    rng = random.Random(seed)
    cell = d / math.sqrt(2)
    gw = int((x2 - x1) / cell) + 1
    gh = int((y2 - y1) / cell) + 1
    grid = [-1] * (gw * gh)
    pts: list[tuple[float, float]] = []
    active: list[int] = []

    def _add(p: tuple[float, float]) -> None:
        gx = int((p[0] - x1) / cell)
        gy = int((p[1] - y1) / cell)
        grid[gy * gw + gx] = len(pts)
        active.append(len(pts))
        pts.append(p)

    _add((x1 + rng.random() * (x2 - x1), y1 + rng.random() * (y2 - y1)))
    while active:
        ai = rng.randrange(len(active))
        px, py = pts[active[ai]]
        placed = False
        for _ in range(k):
            ang = rng.random() * 2 * math.pi
            rad = d * (1 + rng.random())
            nx, ny = px + math.cos(ang) * rad, py + math.sin(ang) * rad
            if not (x1 <= nx < x2 and y1 <= ny < y2):
                continue
            gx, gy = int((nx - x1) / cell), int((ny - y1) / cell)
            ok = True
            for yy in range(max(0, gy - 2), min(gh, gy + 3)):
                for xx in range(max(0, gx - 2), min(gw, gx + 3)):
                    j = grid[yy * gw + xx]
                    if j != -1 and (pts[j][0] - nx) ** 2 + (pts[j][1] - ny) ** 2 < d * d:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                _add((nx, ny))
                placed = True
                break
        if not placed:
            active.pop(ai)
    pts.sort(key=lambda p: (p[1], p[0]))  # сверху вниз — стабильный порядок слотов
    return pts


_zone_points_cache: dict[str, list[tuple[float, float]]] = {}


def _zone_points(zone: str) -> list[tuple[float, float]]:
    """Нормированные [0,1] позиции таверн зоны (blue-noise, детерминированно)."""
    if zone not in _zone_points_cache:
        _zone_points_cache[zone] = _poisson(
            ZONE_RECTS[zone], MIN_DIST, seed=_zone_index(zone) + 1)
    return _zone_points_cache[zone]


def zone_slots(zone: str) -> list[int]:
    """Все слот-id зоны (для assign_map_slot). id = (idx+1)*1000 + 1..N."""
    if zone not in ZONE_RECTS:
        return []
    base = (_zone_index(zone) + 1) * 1000
    return [base + i for i in range(1, len(_zone_points(zone)) + 1)]


def slot_zone(slot_id: int) -> str | None:
    idx = slot_id // 1000 - 1
    return ZONE_ORDER[idx] if 0 <= idx < len(ZONE_ORDER) else None


def slot_norm_pos(slot_id: int) -> tuple[float, float] | None:
    """Нормированная [0,1] позиция таверны слота (для Mini App / интерактивной
    карты — клиент сам переведёт в пиксели по размеру world.png)."""
    zone = slot_zone(slot_id)
    if zone is None:
        return None
    pts = _zone_points(zone)
    local = slot_id % 1000 - 1
    return pts[local] if 0 <= local < len(pts) else None


def region_point(region: str, key: int) -> tuple[float, float] | None:
    """Детерминированная [0,1] точка ВНУТРИ прямоугольника региона по ключу
    (telegram-id владельца). Для таверн без слота: на интерактивной карте лимита
    в 44 слота нет — кластеры разрулят плотность, а позиция стабильна."""
    rect = ZONE_RECTS.get(region)
    if rect is None:
        return None
    x1, y1, x2, y2 = rect
    rng = random.Random(key)
    return (x1 + rng.random() * (x2 - x1), y1 + rng.random() * (y2 - y1))


def _slot_pos(slot_id: int, w: int, h: int) -> tuple[int, int] | None:
    """Пиксельный центр таверны по слоту (из blue-noise точки зоны)."""
    zone = slot_zone(slot_id)
    if zone is None:
        return None
    pts = _zone_points(zone)
    local = slot_id % 1000 - 1
    if not 0 <= local < len(pts):
        return None
    nx, ny = pts[local]
    return int(nx * w), int(ny * h)


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


def _text_size(text: str, font) -> tuple[int, int]:
    left, top, right, bottom = font.getbbox(text)
    return right - left, bottom - top


def _fit_text(text: str, font, max_w: int) -> str:
    """Ужать имя под max_w пикселей по РЕАЛЬНОЙ ширине (а не числу букв), с «…»."""
    if _text_size(text, font)[0] <= max_w:
        return text
    while text and _text_size(text + "…", font)[0] > max_w:
        text = text[:-1]
    return (text + "…") if text else "…"


_font_cache: dict[int, object] = {}


def _cached_font(size: int):
    f = _font_cache.get(size)
    if f is None:
        f = _font(size)
        _font_cache[size] = f
    return f


def _fit_label(text: str, max_w: int, base: int, low: int):
    """Адаптивный шрифт: уменьшаем кегль (base→low), чтобы имя влезло ЦЕЛИКОМ.
    Если даже на минимуме не лезет — обрезаем с «…». Возвращает (текст, шрифт)."""
    size = base
    while size > low:
        f = _cached_font(size)
        if _text_size(text, f)[0] <= max_w:
            return text, f
        size -= 1
    f = _cached_font(low)
    return _fit_text(text, f, max_w), f


def _blit_label(d: ImageDraw.ImageDraw, px: int, py: int, text: str, font) -> None:
    """Подпись с тёмной обводкой, верхний-левый угол в (px, py)."""
    d.text((px, py), text, font=font, fill=(250, 232, 185),
           stroke_width=2, stroke_fill=(35, 18, 5))


def _overlap(a: tuple, b: tuple) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


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
    """Карта с тавернами: blue-noise позиции + коллизийные подписи (PFLP).
    Кэширует по состоянию мира."""
    global _cache_key, _cache_bytes
    key = tuple(sorted((t.slot, t.level, t.name) for t in taverns))
    if key == _cache_key and _cache_bytes is not None:
        return _cache_bytes

    base = Image.open(MAP_FILE).convert("RGBA")
    w, h = base.size
    unit = int(MIN_DIST * min(w, h))           # шаг разброса в px (карта квадратная)
    sprite_w = max(24, int(unit * SPRITE_FRAC))
    # Адаптивная подпись: кегль подбирается под длину имени (base→low).
    base_size = max(14, int(unit * 0.28))
    low_size = max(10, int(unit * 0.15))
    max_label_w = int(unit * 1.9)              # под эту ширину имя ужимается шрифтом

    placed: list[tuple[int, int, MapTavern]] = []
    for t in taverns:
        pos = _slot_pos(t.slot, w, h)
        if pos is not None:
            placed.append((pos[0], pos[1], t))
    placed.sort(key=lambda p: p[1])            # сверху вниз

    # 1) Подложки-«пятаки» под таверны — отдельным полупрозрачным слоем.
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    rr = int(sprite_w * 0.58)
    for cx, cy, _t in placed:
        od.ellipse([cx - rr, cy - int(rr * 0.62), cx + rr, cy + int(rr * 0.62)],
                   fill=(25, 15, 8, 95))
    base = Image.alpha_composite(base, overlay)
    d = ImageDraw.Draw(base)

    # 2) Спрайты + сбор занятых прямоугольников (footprint таверн).
    sprites: dict[int, Image.Image | None] = {}
    occupied: list[tuple[int, int, int, int]] = []
    drawn: list[tuple[int, int, MapTavern, tuple[int, int, int, int]]] = []
    for cx, cy, t in placed:
        tier = sprite_tier(t.level)
        if tier not in sprites:
            sprites[tier] = _load_sprite(tier)
        sprite = sprites[tier]
        if sprite is not None:
            sp = sprite.resize(
                (sprite_w, max(1, int(sprite.height * sprite_w / sprite.width))),
                Image.Resampling.LANCZOS,
            )
            tx, ty = cx - sp.width // 2, cy - int(sp.height * 0.72)
            base.alpha_composite(sp, (tx, ty))
            srect = (tx, ty, tx + sp.width, ty + sp.height)
        else:
            r = sprite_w // 2
            _draw_fallback_marker(d, cx, cy, t.level, r)
            srect = (cx - r, cy - r, cx + r, cy + r)
        occupied.append(srect)
        drawn.append((cx, cy, t, srect))

    # 3) Подписи с выбором кандидат-позиции (PFLP): низ → верх → право → лево →
    # ниже-низ. Берём первую без коллизий и в пределах карты; иначе пропускаем.
    for cx, cy, t, (sx1, sy1, sx2, sy2) in drawn:
        text, lfont = _fit_label(t.name, max_label_w, base_size, low_size)
        lw, lh = _text_size(text, lfont)
        candidates = (
            (cx - lw // 2, sy2 + 3),            # под спрайтом
            (cx - lw // 2, sy1 - lh - 3),       # над спрайтом
            (sx2 + 5, cy - lh // 2),            # справа
            (sx1 - lw - 5, cy - lh // 2),       # слева
            (cx - lw // 2, sy2 + lh + 6),       # ещё ниже
        )
        for px, py in candidates:
            rect = (px - 2, py - 1, px + lw + 2, py + lh + 2)
            if px < 4 or py < 4 or px + lw > w - 4 or py + lh > h - 4:
                continue
            if any(_overlap(rect, o) for o in occupied):
                continue
            _blit_label(d, px, py, text, lfont)
            occupied.append(rect)
            break

    out = io.BytesIO()
    base.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    _cache_key, _cache_bytes = key, out.getvalue()
    return _cache_bytes
