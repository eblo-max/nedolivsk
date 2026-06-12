"""Рейтинг таверн по ВВП. Вызов текстом: «рп топ» (личка и общий чат)."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.game import balance, items

router = Router()

TRIGGERS = {"рп топ", "рптоп", "рп топ 10", "рп топ10", "топ таверн"}


def _is_trigger(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in TRIGGERS


@router.message(StateFilter(None), F.text.func(_is_trigger))
async def show_rating(message: Message, session: AsyncSession) -> None:
    rows = await repo.get_map_taverns(session)  # все таверны с владельцами
    if not rows:
        await message.answer(
            "В Недоливске пока ни одного кабака. Город трезвенников, тоска."
        )
        return

    rated = []
    for tavern, player in rows:
        gdp = balance.tavern_gdp(
            gold=player.gold,
            wood=player.wood,
            grain=player.grain,
            hops=player.hops,
            level=tavern.level,
            income_rate=tavern.income_rate,
            reputation=tavern.reputation,
        )
        gdp += items.gear_value(getattr(player, "equipment", None))
        rated.append((gdp, tavern, player))

    rated.sort(key=lambda x: (-x[0], x[1].name))
    total_gdp = sum(g for g, _, _ in rated)

    top = [
        (i, t.name, p.first_name, t.level, p.region, gdp, t.reputation)
        for i, (gdp, t, p) in enumerate(rated[:10], 1)
    ]
    await message.answer(texts.rating_screen(top, total_gdp, len(rated)))
