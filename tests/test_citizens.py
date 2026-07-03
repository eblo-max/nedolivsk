"""Механика горожан: спавн визитёра не конфликтует с торгом, валидность выбора."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import story_state as ss  # noqa: E402


def _pl(story=None):
    return NS(story=story or {}, level=9, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))


def test_no_visitor_over_active_trade():
    """can_spawn=False при висящем торге — иначе два диалога всплывут разом."""
    now = datetime.now(timezone.utc)
    assert ss.can_spawn(_pl(), now) is True                 # чисто — можно
    assert ss.can_spawn(_pl({"trade": {"good": "ale1"}}), now) is False
    assert ss.can_spawn(_pl({"pending": {"id": "x"}}), now) is False


def test_next_event_gate_blocks_spawn():
    future = (datetime.now(timezone.utc)).replace(year=2099).isoformat()
    assert ss.can_spawn(_pl({"next_event_at": future}), datetime.now(timezone.utc)) is False


def test_resolve_index_bounds_are_api_guarded():
    """resolve сам НЕ защищён от плохого индекса — защита обязана быть в API.
    Регресс: битый/устаревший index (деплой контента) не должен падать 500."""
    import inspect
    from bot.webapi import tavern
    src = inspect.getsource(tavern._api_story_choice)
    assert "bad_choice" in src
    assert "0 <= idx < len(st.choices)" in src
    # int() обёрнут в try (иначе index='abc' → ValueError → 500)
    assert "except (TypeError, ValueError)" in src


def test_faction_decay_scales_with_active():
    """Единый мир: распад растёт с активными (иначе перелив), зажат в коридор."""
    from bot.game import balance as bal
    assert bal.faction_decay_per_hour(0) == bal.FACTION_DECAY_MIN      # пустой мир — пол
    assert bal.faction_decay_per_hour(10**6) == bal.FACTION_DECAY_MAX  # огромный — потолок
    assert bal.faction_decay_per_hour(43) == pytest.approx(43 * bal.FACTION_DECAY_PER_ACTIVE)
    # при живом масштабе (~43 активных) — в «сладкой зоне» симуляции 0.75..1.0/ч
    assert 0.7 <= bal.faction_decay_per_hour(43) <= 1.1


def test_advance_respects_dynamic_decay():
    """Больше распад → сильнее оседает сила фракции за тот же интервал."""
    from bot.game import city as citymod
    now = datetime.now(timezone.utc)

    def mkcity():
        return NS(faction_power={"thieves": 40}, updated_at=now - timedelta(hours=10),
                  situations=[], last_situation_end=None, mood=0)

    slow, fast = mkcity(), mkcity()
    citymod.advance(slow, now, decay_per_hour=0.4)   # 0.4×10 = 4 шага → 36
    citymod.advance(fast, now, decay_per_hour=2.0)   # 2.0×10 = 20 шагов → 20
    assert fast.faction_power["thieves"] < slow.faction_power["thieves"]
    assert slow.faction_power["thieves"] == 36
    assert fast.faction_power["thieves"] == 20


def test_rel_boost_favors_known_citizens():
    """«Город помнит тебя»: знакомые (друзья И враги) заходят чаще случайных,
    но с потолком — чтобы не забивали пул визитов."""
    from bot.game import story_engine as se, balance as bal
    stranger = NS(story={"npc_rel": {}})
    friend = NS(story={"npc_rel": {"buhlo": 30}})
    foe = NS(story={"npc_rel": {"mzdoimov": -60}})
    assert se._rel_boost(stranger, None) == 1.0            # событие без NPC
    assert se._rel_boost(stranger, "buhlo") == 1.0         # незнакомец — базовый вес
    assert se._rel_boost(friend, "buhlo") > 1.0            # друг заходит чаще
    assert se._rel_boost(foe, "mzdoimov") > 1.0            # враг тоже (память о вражде)
    huge = NS(story={"npc_rel": {"buhlo": 100}})
    assert se._rel_boost(huge, "buhlo") == pytest.approx(1.0 + bal.REL_SPAWN_MAX_BOOST)
