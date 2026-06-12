"""Обработка общего чата. В MVP — подсказка идти в личку.

Сюда позже добавятся: мировые события, новости, рейтинги.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import texts

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("start", "tavern", "play"))
async def group_start(message: Message) -> None:
    await message.reply(texts.GROUP_HINT)
