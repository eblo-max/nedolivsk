"""Чистильщик артов экипировки.

Художник экспортирует предметы на «шахматке» (RGB без альфы) — серый фон
впечатан пикселями. Скрипт выбивает этот фон в настоящую прозрачность:
заливкой от краёв по ахроматичным светлым пикселям, чтобы не задеть
светлые блики и серебро ВНУТРИ предмета (они отрезаны цветным контуром).

Запуск:
    python tools/clean_item_art.py            # все файлы в assets/items
    python tools/clean_item_art.py amulet bronya   # только указанные

Идемпотентно: уже прозрачные PNG (с альфой) пропускаются.
"""

import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ITEMS_DIR = Path(__file__).resolve().parent.parent / "assets" / "items"

# Шахматный фон: ахроматичные (R≈G≈B) и средне-светлые пиксели.
ACHROMATIC_MAX_DIFF = 34   # |max(rgb) - min(rgb)| — фон серый, предмет цветной
BG_MIN_BRIGHT = 110        # темнее — это уже предмет/тень
BG_MAX_BRIGHT = 240        # ярче — это белый блик на предмете, не трогаем


def _bg_candidate(arr: np.ndarray) -> np.ndarray:
    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    bright = (r + g + b) // 3
    return (
        (mx - mn <= ACHROMATIC_MAX_DIFF)
        & (bright >= BG_MIN_BRIGHT)
        & (bright <= BG_MAX_BRIGHT)
    )


def _flood_from_border(cand: np.ndarray) -> np.ndarray:
    """Связная заливка фона: только то, что соединено с краем картинки."""
    h, w = cand.shape
    bg = np.zeros((h, w), dtype=bool)
    dq: deque[tuple[int, int]] = deque()

    for x in range(w):
        for y in (0, h - 1):
            if cand[y, x] and not bg[y, x]:
                bg[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if cand[y, x] and not bg[y, x]:
                bg[y, x] = True
                dq.append((y, x))

    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and cand[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                dq.append((ny, nx))
    return bg


def clean(path: Path) -> str:
    img = Image.open(path)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        return "пропущен (уже с прозрачностью)"

    rgb = np.asarray(img.convert("RGB"))
    bg = _flood_from_border(_bg_candidate(rgb))

    alpha = np.where(bg, 0, 255).astype(np.uint8)
    out = np.dstack([rgb, alpha])
    Image.fromarray(out, "RGBA").save(path)
    removed = int(bg.sum())
    pct = 100 * removed / bg.size
    return f"очищен (фон {pct:.0f}%)"


def main(argv: list[str]) -> int:
    if argv:
        files = [ITEMS_DIR / f"{name.removesuffix('.png')}.png" for name in argv]
    else:
        files = sorted(ITEMS_DIR.glob("*.png"))
    for p in files:
        if not p.is_file():
            print(f"  ✗ {p.name}: нет файла")
            continue
        print(f"  • {p.name}: {clean(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
