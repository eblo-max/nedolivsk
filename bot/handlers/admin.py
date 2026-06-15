"""Админ-команды. Работают только для ADMIN_ID из настроек."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot import announce
from bot.config import settings
from bot.db import repo
from bot.db.models import Player, Tavern
from bot.game import balance
from bot.game import world as wld

router = Router()


def _is_admin(message: Message) -> bool:
    return settings.admin_id != 0 and message.from_user.id == settings.admin_id


@router.message(Command("reset"))
async def cmd_reset(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    if not _is_admin(message):
        return  # молча игнорируем чужаков
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Так: /reset <telegram_id>")
        return

    target_id = int(command.args.strip())
    player = await session.get(Player, target_id)
    if player is None:
        await message.answer(f"Игрок {target_id} не найден. Некого сносить.")
        return

    await session.execute(delete(Tavern).where(Tavern.player_id == target_id))
    await repo.delete_player_orders(session, target_id)
    await session.execute(delete(Player).where(Player.id == target_id))
    await message.answer(
        f"🔥 Готово. Игрок {target_id} стёрт подчистую — таверна, золото, "
        "слот на карте. Пусть жмёт /start и начинает с нуля."
    )


@router.message(Command("fair"))
async def cmd_fair(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message):
        return
    world = await repo.get_or_create_world(session)
    wld.open_fair(world)
    await session.flush()  # зафиксировать состояние мира до рассылки
    chat_ids = await repo.all_chat_ids(session)
    await announce.broadcast_fair(message.bot, "open", chat_ids, world)
    await message.answer(
        f"🎪 Ярмарка открыта вручную на {balance.FAIR_DURATION_HOURS} ч. "
        f"Спрос ×{balance.FAIR_DEMAND_MULT:g}. Анонс ушёл в чаты: {len(chat_ids)}."
    )
