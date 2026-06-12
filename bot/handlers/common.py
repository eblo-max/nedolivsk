"""Общие помощники для хендлеров."""

from aiogram.types import FSInputFile, Message

from bot import images, texts
from bot.db.models import Player
from bot.keyboards import inline as kb


async def send_tavern_screen(message: Message, player: Player) -> None:
    """Экран таверны: фото уровня + подпись, либо просто текст, если фото нет."""
    caption = texts.tavern_screen(player, player.tavern)
    markup = kb.tavern_kb(player)
    img = images.tavern_image(player.tavern.level)
    if img is not None:
        await message.answer_photo(
            FSInputFile(img), caption=caption, reply_markup=markup
        )
    else:
        await message.answer(caption, reply_markup=markup)
