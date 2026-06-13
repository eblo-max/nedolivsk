"""Общие помощники для хендлеров."""

import asyncio
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InputFile,
    InputMediaPhoto,
    Message,
)

from bot import autoclean, images, panels, texts
from bot.db.models import Player
from bot.game import character as char
from bot.game import logic
from bot.keyboards import inline as kb

# Кэш file_id: после первой отправки Telegram хранит файл у себя,
# и дальше фото уходит мгновенно, без повторной загрузки.
_file_id_cache: dict[str, str] = {}


def _register_panel(msg: Message, owner_id: int | None) -> None:
    """Закрепить владельца и (в группе) запланировать авто-подчистку."""
    panels.claim(msg, owner_id)
    autoclean.schedule_message(msg)


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
    _register_panel(msg, owner_id)
    return msg


async def show_photo_panel(
    message: Message, media, caption: str, markup, owner_id: int | None = None
) -> Message:
    """Переход в том же окне: подменяем фото панели (edit_media), не двигая
    сообщение. Если оно не фото или правка не прошла — пересоздаём с переносом
    владельца."""
    if message.photo:
        try:
            return await message.edit_media(
                InputMediaPhoto(media=media, caption=caption, parse_mode="HTML"),
                reply_markup=markup,
            )
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return message  # уже показано — панель не трогаем
            # иначе сообщение нельзя редактировать (старое и т.п.) — пересоздаём
    panels.release(message)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    msg = await message.answer_photo(media, caption=caption, reply_markup=markup)
    _register_panel(msg, owner_id)
    return msg


async def show_text_panel(
    message: Message, caption: str, markup, owner_id: int | None = None
) -> Message:
    """Текстовая панель в том же окне (когда нет фоновой картинки)."""
    if message.photo:  # из фото в текст редактированием нельзя — пересоздаём
        panels.release(message)
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        msg = await message.answer(caption, reply_markup=markup)
        _register_panel(msg, owner_id)
        return msg
    try:
        await message.edit_text(caption, reply_markup=markup)
    except TelegramBadRequest:
        pass
    return message


async def show_tavern_panel(
    message: Message, player: Player, owner_id: int | None = None
) -> Message:
    """Экран таверны в текущем окне (переход с куклы обратно к таверне)."""
    caption = texts.tavern_screen(player, player.tavern)
    markup = kb.tavern_kb(player)
    img = images.tavern_image(player.tavern.level)
    if img is None:
        return await show_text_panel(message, caption, markup, owner_id)
    result = await show_photo_panel(message, cached_media(img), caption, markup, owner_id)
    remember_file_id(img, result)
    return result


async def open_tavern(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть главный экран таверны новой панелью (для общего чата)."""
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
    _register_panel(msg, owner_id)
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
    _register_panel(msg, owner_id)
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
