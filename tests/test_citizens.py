"""Механика горожан: спавн визитёра не конфликтует с торгом, валидность выбора."""

import os
from datetime import datetime, timezone
from types import SimpleNamespace as NS

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
