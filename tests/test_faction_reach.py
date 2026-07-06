"""Фракции достижимы ОБЕ стороны через ночную ходку (аудит 06.07.2026: в проде
Корону не задружил НИКТО 0/125, Стража — почти только враги). Ночной выбор теперь
двигает и ЛИЧНУЮ репутацию; у каждой ночной фракции есть путь и вверх, и вниз."""
import os

os.environ.setdefault("BOT_TOKEN", "test:test")

from types import SimpleNamespace as NS  # noqa: E402

from bot.game import balance as bal  # noqa: E402
from bot.game import factions as fx  # noqa: E402
from bot.game import nightrun as nr  # noqa: E402
from bot.game import story_state as ss  # noqa: E402


def _meet_factions() -> dict[str, set[int]]:
    """{фракция: {знаки выборов}} по всем ночным встречам."""
    signs: dict[str, set[int]] = {}
    for enc in nr.MEET_ENCOUNTERS.values():
        for _id, _lbl, _mult, facs in enc["options"]:
            for f, s in facs:
                signs.setdefault(f, set()).add(1 if s > 0 else -1)
    return signs


def test_night_factions_have_both_directions():
    """У КАЖДОЙ фракции (включая купцов) есть ночной выбор + И выбор − — обе стороны."""
    signs = _meet_factions()
    for fac in ("crown", "watch", "church", "thieves", "merchants"):
        assert signs.get(fac) == {1, -1}, f"{fac}: односторонняя ({signs.get(fac)})"


def test_nudge_reaches_friend_and_foe():
    """Повторяемый ночной выбор доводит до «свой» (≤5 раз) и до «враг» в обратную."""
    nudge = bal.NIGHTRUN_FACTION_NUDGE
    up = NS(story={})
    steps = 0
    while fx.rank(up, "crown") < 1 and steps < 10:
        ss.adjust_faction(up, "crown", nudge)
        steps += 1
    assert fx.rank(up, "crown") >= 1 and steps <= 5, f"«свой» не достигнут за {steps}"

    down = NS(story={})
    steps = 0
    while fx.rank(down, "watch") > -2 and steps < 40:
        ss.adjust_faction(down, "watch", -nudge)
        steps += 1
    assert fx.rank(down, "watch") == -2, "«враг» недостижим"


def test_friendly_choice_loot_not_brutal():
    """Дружелюбный выбор больше не режет добычу вдвое (был 0.6/0.7 → стал ≥0.8)."""
    for enc in nr.MEET_ENCOUNTERS.values():
        for _id, _lbl, mult, facs in enc["options"]:
            if any(s > 0 for _f, s in facs):        # выбор в плюс фракции
                assert mult >= 0.8, f"{_id}: дружба режет добычу до {mult}"
