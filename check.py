"""Проверка проекта перед коммитом: python check.py

Ловит обрезанные файлы (главная беда), битый синтаксис и потерянные хвосты.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# Маркер из конца каждого файла: если его нет — файл обрезан
TAIL_MARKERS = {
    "bot/config.py": "settings = Settings()",
    "bot/main.py": "asyncio.run(main())",
    "bot/middlewares.py": "raise",
    "bot/images.py": "return best",
    "bot/texts.py": "join(lines)",
    "bot/notifier.py": "await session.commit()",
    "bot/game/balance.py": "reputation * 3",
    "bot/game/logic.py": "new_level=tavern.level)",
    "bot/game/worldmap.py": "return _cache_bytes",
    "bot/db/base.py": "ALTER TABLE",
    "bot/db/models.py": 'back_populates="tavern")',
    "bot/db/repo.py": "return list(result.all())",
    "bot/handlers/start.py": "await callback.answer()",
    "bot/handlers/tavern.py": "callback.answer(",
    "bot/handlers/common.py": "reply_markup=markup)",
    "bot/handlers/group.py": "GROUP_HINT)",
    "bot/handlers/admin.py": "/start",
    "bot/handlers/rating.py": "rating_screen(top, total_gdp, len(rated))",
    "bot/handlers/worldmap_cmd.py": "caption=caption",
    "bot/keyboards/inline.py": "return kb.as_markup()",
}


def main() -> int:
    errors = []
    for p in sorted((ROOT / "bot").rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            errors.append(f"{rel}: битая кодировка ({e})")
            continue
        try:
            ast.parse(src)
        except SyntaxError as e:
            errors.append(f"{rel}: синтаксис, строка {e.lineno}: {e.msg}")
            continue
        marker = TAIL_MARKERS.get(rel)
        if marker and marker not in src.split("def ")[-1] and marker not in src[-600:]:
            errors.append(f"{rel}: похоже, обрезан (нет '{marker}' в конце)")

    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("aiogram", "SQLAlchemy", "asyncpg", "pydantic-settings", "Pillow"):
        if pkg.lower() not in req.lower():
            errors.append(f"requirements.txt: пропал {pkg}")
    if not req.endswith("\n"):
        errors.append("requirements.txt: нет перевода строки в конце (склейка пакетов)")

    if errors:
        print("ПРОВЕРКА ПРОВАЛЕНА:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("OK: все файлы целы, можно коммитить")
    return 0


if __name__ == "__main__":
    sys.exit(main())
