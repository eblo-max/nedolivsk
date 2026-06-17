"""Рейтинг таверн по ВВП. Вызов текстом: «рп топ» (личка и общий чат)."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.game import balance, buildings, items, production
from bot.handlers import common

router = Router()

TRIGGERS = {"рп топ", "рптоп", "рп топ 10", "рп топ10", "топ таверн"}


def _is_trigger(text: str | None) -> bool:
    return bool(text) and text.strip().lower() in TRIGGERS


@router.message(StateFilter(None), F.text.func(_is_trigger))
async def show_rating(message: Message, session: AsyncSession) -> Message:
    rows = await repo.get_map_taverns(session)  # все таверны с владельцами
    if not rows:
        return await message.answer(
            "В Недоливске пока ни одного кабака. Город трезвенников, тоска."
        )

    rated = []
    for tavern, player in rows:
        gdp = balance.tavern_gdp(
            inventory=player.inventory,
            gold=player.gold,
            level=tavern.level,
            income_rate=tavern.income_rate,
            reputation=tavern.reputation,
        )
        gdp += items.gear_value(getattr(player, "equipment", None))
        gdp += buildings.invested_value(tavern)
        gdp += production.products_value(tavern)
        rated.append((gdp, tavern, player))

    rated.sort(key=lambda x: (-x[0], x[1].name))
    total_gdp = sum(g for g, _, _ in rated)

    top = [
        (i, t.name, p.first_name, t.level, p.region, gdp, t.reputation)
        for i, (gdp, t, p) in enumerate(rated[:10], 1)
    ]
    text = texts.rating_screen(top, total_gdp, len(rated))
    img = images.named_image("VVP")
    if img is None:
        return await message.answer(text)
    media = common.cached_media(img)
    if len(text) <= common._CAPTION_LIMIT:          # доска целиком влезает в подпись
        sent = await message.answer_photo(media, caption=text)
        common.remember_file_id(img, sent)
        return sent
    # редкий случай длинной доски — баннер + полный текст отдельным сообщением
    banner = await message.answer_photo(media, caption="🏆 Доска почёта Недоливска")
    common.remember_file_id(img, banner)
    return await message.answer(text)
