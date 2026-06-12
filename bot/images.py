"""Картинки таверны по уровням.

Файлы кладутся в assets/ как tavern_1.jpg, tavern_2.jpg, ...
Если для уровня нет своей картинки — берётся ближайшая снизу.
"""

from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_EXTENSIONS = ("jpg", "jpeg", "png")


def tavern_image(level: int) -> Path | None:
    best: Path | None = None
    for lvl in range(1, level + 1):
        for ext in _EXTENSIONS:
            p = ASSETS_DIR / f"tavern_{lvl}.{ext}"
            if p.is_file():
                best = p
                break
    return best
