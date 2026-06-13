"""Движок живого города: подбор события под контекст, показ, резолв исхода.

Игрок-локальные мутации (эффекты, очередь, кулдаун, pending) делает движок.
Ввод-вывод (эхо в чат, запись в летопись) — на стороне хендлера: он получает
ctx с собранными строками.
"""

import random
from datetime import datetime

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Player
from bot.game import balance, npc, story_state
from bot.game.story_content import STORYLETS
from bot.game.story_defs import Ctx, Storylet


def get(storylet_id: str) -> Storylet | None:
    return STORYLETS.get(storylet_id)


def _eligible(s: Storylet, ctx: Ctx) -> bool:
    if s.scheduled_only:
        return False
    return all(p.check(ctx) for p in s.preconditions)


def _choice_available(choice, ctx: Ctx) -> bool:
    return all(p.check(ctx) for p in choice.requires)


def select(player: Player, city, rng: random.Random) -> Storylet | None:
    """Выбрать случайное подходящее событие (по весам)."""
    ctx = Ctx(player=player, city=city)
    pool = [s for s in STORYLETS.values() if _eligible(s, ctx)]
    if not pool:
        return None
    return rng.choices(pool, weights=[s.weight for s in pool])[0]


def maybe_spawn(
    player: Player, city, now: datetime, rng: random.Random | None = None
) -> Storylet | None:
    """Кулдаун + шанс + подбор. Ставит событие в pending. None — не сейчас."""
    rng = rng or random
    if not story_state.can_spawn(player, now):
        return None
    if rng.random() >= balance.EVENT_CHANCE:
        return None
    s = select(player, city, rng)
    if s is not None:
        story_state.set_pending(player, s.id, s.npc)
    return s


def pending_storylet(player: Player) -> Storylet | None:
    p = story_state.get_pending(player)
    return get(p["id"]) if p else None


def present(s: Storylet, player: Player, city=None) -> tuple[str, InlineKeyboardMarkup]:
    """Текст события + клавиатура выборов (индексы — по полному списку choices)."""
    ctx = Ctx(player=player, city=city)
    head = f"{npc.label(s.npc)}\n\n" if s.npc else ""
    text = f"{head}<b>{s.title}</b>\n{s.text}"
    kb = InlineKeyboardBuilder()
    for i, choice in enumerate(s.choices):
        if _choice_available(choice, ctx):
            kb.button(text=choice.label, callback_data=f"ev:{i}")
    kb.button(text="🚪 Не сейчас", callback_data="ev:skip")
    kb.adjust(1)
    return text, kb.as_markup()


def resolve(
    player: Player, city, s: Storylet, choice_index: int,
    now: datetime, rng: random.Random | None = None, shielded: bool = False,
):
    """Резолв выбора: бросок исхода, применение эффектов, финализация игрока.
    Возвращает (Outcome, Ctx) — у Ctx собраны эхо/летопись/отложенные."""
    rng = rng or random
    choice = s.choices[choice_index]
    ctx = Ctx(player=player, city=city, shielded=shielded)
    if not _choice_available(choice, ctx):
        return None, ctx
    outcome = rng.choices(
        choice.outcomes, weights=[o.weight for o in choice.outcomes]
    )[0]
    for eff in outcome.effects:
        eff.apply(ctx)
    for sid, hours in ctx.scheduled:
        story_state.queue_push(player, sid, hours)
    story_state.clear_pending(player)
    story_state.set_last_event(player, now)
    return outcome, ctx
