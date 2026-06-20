"""Команда /map — мировая карта с тавернами игроков."""

import asyncio
from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo
from bot.game import worldmap
from bot.keyboards.inline import world_map_kb

router = Router()


@router.message(Command("map", "karta"))
async def cmd_map(message: Message, session: AsyncSession) -> None:
    rows = await repo.get_map_taverns(session)

    placed: list[worldmap.MapTavern] = []
    homeless: list[str] = []
    for tavern, player in rows:
        slot = tavern.map_slot
        if slot is None:
            slot = await repo.assign_map_slot(session, tavern, player.region)
        if slot is not None:
            placed.append(
                worldmap.MapTavern(slot=slot, level=tavern.level, name=tavern.name)
            )
        else:
            homeless.append(tavern.name)

    # рендер тяжёлый — уводим в поток, чтобы не блокировать бота
    img = await asyncio.to_thread(worldmap.render, placed)
    caption = f"🗺 <b>Недоливск — карта мира</b>\nТаверн на карте: {len(placed)}"
    if homeless:
        caption += "\n⛺ Ждут места: " + ", ".join(
            escape(n) for n in homeless[:5]
        )
    # кнопка на ЖИВУЮ интерактивную карту (личка — web_app; группа — Direct-Link)
    private = message.chat.type == "private"
    kb = world_map_kb(private)
    if kb is None and not private:
        caption += "\n\n🗺 <i>Живая интерактивная карта — открой бота в личке.</i>"
    else:
        caption += "\n\n👇 <b>Открой живую интерактивную карту</b> — зум, таверны, ивенты."
    return await message.answer_photo(
        BufferedInputFile(img, filename="nedolivsk_map.jpg"),
        caption=caption, reply_markup=kb,
    )
