"""Слэш-команды-навигация по механикам — открыть раздел из «/»-меню.

Работают и в личке, и в общем чате. В группе панель закрепляется за владельцем
(PanelGuard) и подчищается автоклином — как «гг …». Рендер переиспользует тексты
и клавиатуры разделов; кнопки на них обрабатывают существующие cb-хендлеры.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import autoclean, panels, texts
from bot.db import repo
from bot.handlers.rating import show_rating
from bot.keyboards import inline as kb

router = Router()


async def _send(message: Message, text: str, markup=None) -> None:
    """Отправить раздел: в группе — за владельцем и с автоподчисткой."""
    if panels.is_group(message):
        sent = await message.reply(text, reply_markup=markup)
        panels.claim(sent, message.from_user.id)
        autoclean.schedule_message(sent)
        autoclean.schedule_message(message)  # подчистить сам триггер
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("top", "reyting"))
async def cmd_top(message: Message, session: AsyncSession) -> None:
    sent = await show_rating(message, session)
    if panels.is_group(message) and sent is not None:
        panels.claim(sent, message.from_user.id)
        autoclean.schedule_message(sent)
        autoclean.schedule_message(message)


@router.message(Command("market", "bazar"))
async def cmd_market(message: Message, session: AsyncSession) -> None:
    # Рынок ЕДИНЫЙ для всех — цены не зависят от чата/игрока.
    world = await repo.get_or_create_world(session)
    await _send(message, texts.market_screen(world), kb.market_kb())


@router.message(Command("auction", "torgi"))
async def cmd_auction(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if player is None or not player.tavern:
        await _send(message, "Сначала заведи кабак: /start")
        return
    await _send(message, texts.auction_screen(player.tavern),
                kb.auction_kb(player.tavern))


@router.message(Command("city", "gorod"))
async def cmd_city(message: Message, session: AsyncSession) -> None:
    city = await repo.get_world_city(session)   # единый мир — город у всех общий
    await _send(message, texts.city_screen(city), kb.city_kb())


@router.message(Command("chronicle", "letopis"))
async def cmd_chronicle(message: Message, session: AsyncSession) -> None:
    entries = await repo.recent_chronicle(session, repo.GLOBAL_CITY_ID, 10)
    await _send(message, texts.chronicle_screen(entries), kb.chronicle_kb())


@router.message(Command("citizens", "reputaciya"))
async def cmd_citizens(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if player is None:
        await _send(message, "Сначала заведи кабак: /start")
        return
    await _send(message, texts.citizens_screen(player), kb.citizens_kb())


@router.message(Command("hunt", "ohota"))
async def cmd_hunt(message: Message, session: AsyncSession) -> None:
    player = await repo.get_player(session, message.from_user.id)
    if player is None or not player.tavern:
        await _send(message, "Сначала заведи кабак: /start")
        return
    await _send(message, texts.hunt_menu(player), kb.hunt_menu_kb(player))
