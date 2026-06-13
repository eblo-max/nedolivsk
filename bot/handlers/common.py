"""Общие помощники для хендлеров."""

import asyncio
from pathlib import Path

from aiogram.types import BufferedInputFile, FSInputFile, InputFile, Message

from bot import images, panels, texts
from bot.db.models import Player
from bot.game import character as char
from bot.game import logic
from bot.keyboards import inline as kb

# Кэш file_id: после первой отправки Telegram хранит файл у себя,
# и дальше фото уходит мгновенно, без повторной загрузки.
_file_id_cache: dict[str, str] = {}


def cached_media(img: Path) -> str | InputFile:
    return _file_id_cache.get(str(img)) or FSInputFile(img)


def remember_file_id(img: Path, message: Message | None) -> None:
    if message is not None and message.photo:
        _file_id_cache[str(img)] = message.photo[-1].file_id


async def send_tavern_screen(
    message: Message, player: Player, owner_id: int | None = None
) -> Message:
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
        msg = await message.answer(caption, reply_markup=markup)
    panels.claim(msg, owner_id)
    return msg


async def open_tavern(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть главный экран таверны панелью (для общего чата)."""
    return await send_tavern_screen(message, player, owner_id=owner_id)


async def open_warehouse(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть склад отдельной панелью (фон — картинка таверны)."""
    caption = texts.warehouse_screen(player, player.tavern)
    markup = kb.back_kb()
    img = images.tavern_image(player.tavern.level)
    if img is not None:
        msg = await message.answer_photo(
            cached_media(img), caption=caption, reply_markup=markup
        )
        remember_file_id(img, msg)
    else:
        msg = await message.answer(caption, reply_markup=markup)
    panels.claim(msg, owner_id)
    return msg


async def _send_character_panel(
    message: Message, player: Player, caption: str, markup, owner_id: int | None
) -> Message:
    if char.background_exists():
        img = await asyncio.to_thread(char.render, player.equipment)
        msg = await message.answer_photo(
            BufferedInputFile(img, filename="character.jpg"),
            caption=caption,
            reply_markup=markup,
        )
    else:
        msg = await message.answer(caption, reply_markup=markup)
    panels.claim(msg, owner_id)
    return msg


async def open_character(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть экран персонажа отдельной панелью (кукла + кузница)."""
    state, _ = logic.craft_state(player)
    caption = texts.character_screen(player, texts.craft_line(player))
    markup = kb.character_kb(craft_ready=(state == "ready"))
    return await _send_character_panel(message, player, caption, markup, owner_id)


async def open_forge(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть кузницу отдельной панелью."""
    return await _send_character_panel(
        message, player, texts.forge_screen(player), kb.forge_kb(player), owner_id
    )
