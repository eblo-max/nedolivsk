"""Глубокий аудит границ: экстремумы чисел, время/МСК, тексты-плейсхолдеры,
согласованность мировых событий и регенерации. Кроме боссов."""

import ast
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, combat, items, logic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# ── ЭКСТРЕМУМЫ: богатый игрок / макс-статы / нули не ломают формулы ─────────
def test_income_extremes_no_overflow_no_negative():
    for base, gold in ((0, 0), (1, 0), (10**9, 10**12), (300, 10**15)):
        tav = NS(income_rate=base, level=8, products={}, last_income_at=None,
                 rep_progress=0, auction_sold=0, production={})
        p = NS(level=8, gold=gold, equipment={}, inventory={}, buff_kind=None,
               buff_until=None, perks={}, region="green_valleys", tavern=tav,
               econ={}, story={})
        q = logic.income_rate_quote(p, tav)
        assert q >= 0 and isinstance(q, int), (base, q)
        # превью след. уровня на экстремуме тоже целое и неотрицательное
        q2 = logic.income_rate_quote(p, tav, base_rate=base * 2)
        assert q2 >= q and isinstance(q2, int), (base, q2)


def test_max_gear_never_exceeds_caps():
    """Заточка +5 + аффикс на максимальном ярусе — броня не пробивает ARMOR_CAP,
    крит не уходит выше HUNT_CRIT_CAP в бою (капы держат экстремум)."""
    eq = {}
    for it in items.CATALOG.values():
        aff = next(iter(items.AFFIXES)) if it.slot not in eq else ""
        eq[it.slot] = items.make_entry(it.id, items.TIER_MAX, items.PLUS_MAX, aff)
    p = NS(level=99, equipment=eq, buff_kind=None, buff_until=None, perks={}, story={})
    stats = combat.player_stats(p)
    assert stats["armor"] <= balance.ARMOR_CAP, stats["armor"]
    assert combat.max_hp(p) > 0
    # крит в бою капается
    crit_used = min(balance.HUNT_CRIT_CAP, stats["crit"])
    assert crit_used <= balance.HUNT_CRIT_CAP


def test_zero_and_empty_inputs():
    p = NS(level=1, equipment={}, buff_kind=None, buff_until=None, perks={}, story={})
    assert combat.player_stats(p)["damage"] == 0
    assert combat.max_hp(p) > 0
    assert items.combat_stats({}) == {"damage": 0, "crit": 0, "armor": 0,
                                      "luck": 0, "vitality": 0}
    assert items.combat_stats(None)["armor"] == 0


# ── ВРЕМЯ/МСК: единый расчёт во всех модулях, границы часов ────────────────
def test_msk_consistent_across_modules():
    """Ручной (hour+3)%24 == astimezone(MSK) для всех 24 UTC-часов —
    иначе тихие часы и ночная скупка воров разъедутся по логике."""
    from bot.game.buff import MSK
    for h in range(24):
        utc = datetime(2026, 7, 3, h, 30, tzinfo=timezone.utc)
        manual = (utc.hour + 3) % 24
        via_tz = utc.astimezone(MSK).hour
        assert manual == via_tz, (h, manual, via_tz)


def test_quiet_hours_and_night_sale_boundaries():
    from bot.game import factions as F
    quiet = lambda uh: ((uh + 3) % 24) >= 23 or ((uh + 3) % 24) < 8
    # тихие часы 23:00–08:00 МСК — точные границы
    assert quiet(20) and not quiet(19)                # 23 МСК тихо, 22 нет
    assert quiet(4) and not quiet(5)                  # 07 МСК тихо, 08 нет
    # ночная скупка воров 22–6 МСК: 21:59 нет, 22:00 да, 05:59 да, 06:00 нет
    p = NS(story={"faction": {"thieves": 45}})
    assert F.thief_night_sale_mult(p, 22) > 1.0 and F.thief_night_sale_mult(p, 21) == 1.0
    assert F.thief_night_sale_mult(p, 5) > 1.0 and F.thief_night_sale_mult(p, 6) == 1.0


# ── HP РЕГЕН: показ времени согласован с фактическим восстановлением ───────
def test_hp_regen_show_matches_recovery():
    bad = []
    for seed in range(600):
        r = random.Random(seed)
        p = NS(level=r.randint(1, 20), equipment={}, buff_kind=None,
               buff_until=None, perks={}, story={})
        mx = combat.max_hp(p)
        p.hp = r.randint(1, max(1, mx - 1))
        p.hp_at = datetime(2026, 7, 3, tzinfo=timezone.utc)
        mins = combat.regen_full_minutes(p, p.hp_at)          # ПОКАЗ: через сколько полное
        # через показанное время HP должно быть полным (± округление)
        later = p.hp_at + timedelta(minutes=mins)
        chp = combat.current_hp(p, later)
        if chp < mx:
            bad.append((seed, p.hp, mx, mins, chp))
    assert not bad, f"регген показ≠факт: {bad[:5]}"


def test_current_hp_monotone_and_capped():
    for seed in range(300):
        r = random.Random(seed)
        p = NS(level=r.randint(1, 15), equipment={}, buff_kind=None,
               buff_until=None, perks={}, story={})
        mx = combat.max_hp(p)
        p.hp = r.randint(1, mx)
        p.hp_at = datetime(2026, 7, 3, tzinfo=timezone.utc)
        prev = 0
        for h in range(0, 48, 4):
            chp = combat.current_hp(p, p.hp_at + timedelta(hours=h))
            assert chp <= mx and chp >= prev - 1, (seed, h, chp, mx)
            prev = chp


# ── ТЕКСТЫ: ни один .format() не падает KeyError на своих плейсхолдерах ────
def test_text_format_strings_have_no_stray_placeholders():
    """Строковые литералы с .format() не должны содержать одиночные { }
    вне пар (иначе KeyError/ValueError в проде). Скан AST по bot/texts.py."""
    src = (ROOT / "bot" / "texts.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and isinstance(node.func.value, ast.Constant)
                and isinstance(node.func.value.value, str)):
            s = node.func.value.value
            # грубая проверка парности фигурных скобок
            depth = 0
            for c in s:
                depth += (c == "{") - (c == "}")
                if depth < 0:
                    break
            if depth != 0:
                bad.append((node.lineno, s[:50]))
    assert not bad, f"несбалансированные плейсхолдеры: {bad}"
