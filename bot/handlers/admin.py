"""Админ-команды. Работают только для ADMIN_ID из настроек."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.models import Player, Tavern

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
    await session.execute(delete(Player).where(Player.id == target_id))
    await message.answer(
        f"🔥 Готово. Игрок {target_id} стёрт подчистую — таверна, золото, "
        "слот на карте. Пусть жмёт /start и начинает с нуля."
    )
