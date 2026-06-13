"""Реестр владельцев панелей в общих чатах.

В личке всё однозначно — собеседник один. В группе же у каждой панели
(сообщения бота с кнопками) есть владелец: тот, кто её открыл. Кнопки
жмёт только он. Храним соответствие (chat_id, message_id) -> user_id.

Память живёт в процессе: после рестарта бота старые групповые панели
«протухают» (владелец неизвестен) — middleware попросит открыть заново.
"""

from aiogram.types import Message

_owners: dict[tuple[int, int], int] = {}


def is_group(message: Message | None) -> bool:
    return bool(message) and message.chat.type in ("group", "supergroup")


def claim(message: Message | None, owner_id: int | None) -> None:
    """Закрепить панель за владельцем (только в группе)."""
    if owner_id is not None and is_group(message):
        _owners[(message.chat.id, message.message_id)] = owner_id


def release(message: Message | None) -> None:
    """Забыть панель (например, перед её пересозданием)."""
    if is_group(message):
        _owners.pop((message.chat.id, message.message_id), None)


def owner_of(chat_id: int, message_id: int) -> int | None:
    return _owners.get((chat_id, message_id))
