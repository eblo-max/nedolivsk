"""Общие помощники для хендлеров."""

import asyncio
from collections import OrderedDict
from html import escape
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
from bot.game import balance, buff
from bot.game import character as char
from bot.game import logic, storehouse
from bot.keyboards import inline as kb

# Лимит подписи к фото в Telegram — 1024 UTF-16 code units (не 4096, как у текста).
_CAPTION_LIMIT = 1024


def _u16len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def clamp_caption(text: str, limit: int = _CAPTION_LIMIT) -> str:
    """Подстраховка: не дать подписи превысить лимит Telegram (иначе панель
    падает и сносится). Режем ЦЕЛЫМИ строками с конца — теги у нас всегда
    открыты-закрыты в пределах одной строки, так что HTML остаётся валидным."""
    if _u16len(text) <= limit:
        return text
    lines = text.split("\n")
    while len(lines) > 1 and _u16len("\n".join(lines)) > limit - 1:
        lines.pop()
    out = "\n".join(lines)
    while out and _u16len(out) > limit - 1:  # одна сверхдлинная строка (страховка)
        out = out[:-1]
    return out + "…"


# Кэш file_id статичных картинок (по пути файла).
_file_id_cache: dict[str, str] = {}

# Кэш file_id ДИНАМИЧЕСКИХ картинок (кукла, складская ведомость) по состоянию.
# Тот же состав экипировки / инвентаря → Telegram переиспользует файл,
# без перерисовки и повторной загрузки. LRU, живёт в процессе.
_DYN_MAX = 256
_dyn_ids: "OrderedDict[tuple, str]" = OrderedDict()


def _get_dyn(key: tuple) -> str | None:
    fid = _dyn_ids.get(key)
    if fid is not None:
        _dyn_ids.move_to_end(key)
    return fid


def remember_media(key: tuple, msg: Message | None) -> None:
    """Запомнить file_id отправленной динамической картинки."""
    if msg is not None and msg.photo:
        _dyn_ids[key] = msg.photo[-1].file_id
        _dyn_ids.move_to_end(key)
        while len(_dyn_ids) > _DYN_MAX:
            _dyn_ids.popitem(last=False)


async def doll_media(player: Player):
    """(media, key, need_capture) для куклы: file_id из кэша или свежий рендер."""
    key = ("doll",) + tuple(sorted((player.equipment or {}).items()))
    fid = _get_dyn(key)
    if fid:
        return fid, key, False
    img = await asyncio.to_thread(char.render, player.equipment)
    return BufferedInputFile(img, filename="character.jpg"), key, True


async def sklad_media(player: Player):
    """(media, key, need_capture) для складской ведомости."""
    inv = player.inventory or {}
    key = ("sklad",) + tuple(sorted((r, int(inv.get(r, 0))) for r in balance.RESOURCES))
    fid = _get_dyn(key)
    if fid:
        return fid, key, False
    img = await asyncio.to_thread(storehouse.render, player.inventory)
    return BufferedInputFile(img, filename="sklad.jpg"), key, True


def _register_panel(msg: Message, owner_id: int | None) -> None:
    """Закрепить владельца и (в группе) запланировать авто-подчистку."""
    panels.claim(msg, owner_id)
    autoclean.schedule_message(msg)


def mention(player: Player) -> str:
    """HTML-упоминание игрока со ссылкой-пингом (tg://user). Для тегов в чате."""
    name = escape(player.first_name or "Хозяин")
    return f'<a href="tg://user?id={player.id}">{name}</a>'


def tag_in_group(message: Message, player: Player, text: str) -> str:
    """В группе — префикс с тегом игрока (чтобы пинговало, как подкидыш);
    в личке — текст как есть."""
    if panels.is_group(message):
        return f"{mention(player)}!\n\n{text}"
    return text


def cached_media(img: Path) -> str | InputFile:
    return _file_id_cache.get(str(img)) or FSInputFile(img)


def remember_file_id(img: Path, message: Message | None) -> None:
    if message is None:
        return
    if message.photo:
        _file_id_cache[str(img)] = message.photo[-1].file_id
    elif message.video:
        _file_id_cache[str(img)] = message.video.file_id


async def send_tavern_screen(
    message: Message, player: Player, owner_id: int | None = None
) -> Message:
    """Экран таверны: фото уровня + подпись, либо просто текст, если фото нет."""
    buff.refresh(player)  # прокрутить ежедневный бонус (выдать/сжечь/снять баф)
    caption = texts.tavern_screen(player, player.tavern)
    markup = kb.tavern_kb(player)
    img = images.tavern_image(player.tavern.level)
    if img is not None:
        msg = await message.answer_photo(
            cached_media(img), caption=clamp_caption(caption), reply_markup=markup
        )
        remember_file_id(img, msg)
    else:
        msg = await message.answer(caption, reply_markup=markup)
    _register_panel(msg, owner_id)
    return msg


async def caption_edit(message: Message, text: str, markup) -> None:
    """Правит подпись к фото или текст сообщения — что есть."""
    try:
        if message.photo:
            await message.edit_caption(caption=clamp_caption(text), reply_markup=markup)
        else:
            await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # не изменилось — Telegram не любит одинаковые правки


async def show_image_panel(
    message: Message, img_path: Path | None, caption: str, markup,
    owner_id: int | None = None,
) -> Message:
    """Панель со статичной картинкой (по пути файла) в том же окне.
    Нет картинки — правим только подпись/текст."""
    if img_path is None:
        await caption_edit(message, caption, markup)
        return message
    result = await show_photo_panel(message, cached_media(img_path), caption, markup, owner_id)
    remember_file_id(img_path, result)
    return result


async def show_photo_panel(
    message: Message, media, caption: str, markup, owner_id: int | None = None
) -> Message:
    """Переход в том же окне: подменяем фото панели (edit_media), не двигая
    сообщение. Если оно не фото или правка не прошла — пересоздаём с переносом
    владельца."""
    caption = clamp_caption(caption)
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
    buff.refresh(player)  # прокрутить ежедневный бонус (выдать/сжечь/снять баф)
    caption = texts.tavern_screen(player, player.tavern)
    markup = kb.tavern_kb(player)
    img = images.tavern_image(player.tavern.level)
    if img is None:
        return await show_text_panel(message, caption, markup, owner_id)
    result = await show_photo_panel(message, cached_media(img), caption, markup, owner_id)
    remember_file_id(img, result)
    return result


def _warehouse_img(player: Player) -> Path | None:
    """Картинка склада, а если её нет — фон таверны."""
    return images.warehouse_image() or images.tavern_image(player.tavern.level)


async def show_warehouse_panel(
    message: Message, player: Player, owner_id: int | None = None
) -> Message:
    """Склад в текущем окне: складская ведомость с ресурсами (edit_media)."""
    markup = kb.back_kb()
    if storehouse.background_exists():
        media, key, need_capture = await sklad_media(player)
        caption = texts.storehouse_caption(player, player.tavern)
        result = await show_photo_panel(message, media, caption, markup, owner_id)
        if need_capture:
            remember_media(key, result)
        return result
    # фолбэк: картинка-фон + полный текстовый список
    caption = texts.warehouse_screen(player, player.tavern)
    img = _warehouse_img(player)
    if img is None:
        return await show_text_panel(message, caption, markup, owner_id)
    result = await show_photo_panel(message, cached_media(img), caption, markup, owner_id)
    remember_file_id(img, result)
    return result


async def open_tavern(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть главный экран таверны новой панелью (для общего чата)."""
    return await send_tavern_screen(message, player, owner_id=owner_id)


async def open_warehouse(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть склад новой панелью (складская ведомость с ресурсами)."""
    markup = kb.back_kb()
    if storehouse.background_exists():
        media, key, need_capture = await sklad_media(player)
        msg = await message.answer_photo(
            media,
            caption=clamp_caption(texts.storehouse_caption(player, player.tavern)),
            reply_markup=markup,
        )
        if need_capture:
            remember_media(key, msg)
        _register_panel(msg, owner_id)
        return msg
    # фолбэк
    caption = texts.warehouse_screen(player, player.tavern)
    img = _warehouse_img(player)
    if img is not None:
        msg = await message.answer_photo(
            cached_media(img), caption=clamp_caption(caption), reply_markup=markup
        )
        remember_file_id(img, msg)
    else:
        msg = await message.answer(caption, reply_markup=markup)
    _register_panel(msg, owner_id)
    return msg


async def _send_character_panel(
    message: Message, player: Player, caption: str, markup, owner_id: int | None
) -> Message:
    if not char.background_exists():
        msg = await message.answer(caption, reply_markup=markup)
        _register_panel(msg, owner_id)
        return msg
    media, key, need_capture = await doll_media(player)
    msg = await message.answer_photo(media, caption=clamp_caption(caption),
                                     reply_markup=markup)
    if need_capture:
        remember_media(key, msg)
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


async def open_bonus(message: Message, player: Player, owner_id: int) -> Message:
    """Открыть экран ежедневного бонуса отдельной панелью."""
    buff.refresh(player)
    msg = await message.answer(
        texts.bonus_screen(player), reply_markup=kb.bonus_kb(player))
    _register_panel(msg, owner_id)
    return msg
