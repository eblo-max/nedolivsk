"""Общие помощники для хендлеров."""

from pathlib import Path

from aiogram.types import FSInputFile, InputFile, Message

from bot import images, texts
from bot.db.models import Player
from bot.keyboards import inline as kb

# Кэш file_id: после первой отправки Telegram хранит файл у себя,
# и дальше фото уходит мгновенно, без повторной загрузки.
_file_id_cache: dict[str, str] = {}


def cached_media(img: Path) -> str | InputFile:
    return _file_id_cache.get(str(img)) or FSInputFile(img)


def remember_file_id(img: Path, message: Message | None) -> None:
    if message is not None and message.photo:
        _file_id_cache[str(img)] = message.photo[-1].file_id


async def send_tavern_screen(message: Message, player: Player) -> None:
    """Экран таверны: фото уровня + подпись, либо просто текст, если фото нет."""
    caption = texts.tavern_screen(player, player.tavern)
    markup = kb.tavern_kb(player)
    img = images.tavern_image(player.tavern.level)
    if img is not None:
        msg = await message.answer_photo(
            cached_media(img), caption=caption, reply_markup=markup
        )
        remember_file_id(img, msg)
    else:
        await message.answer(caption, reply_markup=markup)
