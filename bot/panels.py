"""Реестр владельцев панелей в общих чатах.

В личке всё однозначно — собеседник один. В группе же у каждой панели
(сообщения бота с кнопками) есть владелец: тот, кто её открыл. Кнопки
жмёт только он. Храним соответствие (chat_id, message_id) -> user_id.

Память живёт в процессе: после рестарта бота старые групповые панели
«протухают» (владелец неизвестен) — middleware попросит открыть заново.
"""

from collections import OrderedDict

from aiogram.types import Message

# LRU: брошенные/старые панели вытесняются. При вытеснении кнопка ответит
# «панель устарела» — игрок просто откроет заново. Память ограничена.
_MAX_PANELS = 4000
_owners: "OrderedDict[tuple[int, int], int]" = OrderedDict()


def is_group(message: Message | None) -> bool:
    return bool(message) and message.chat.type in ("group", "supergroup")


def claim(message: Message | None, owner_id: int | None) -> None:
    """Закрепить панель за владельцем (только в группе)."""
    if owner_id is not None and is_group(message):
        key = (message.chat.id, message.message_id)
        _owners[key] = owner_id
        _owners.move_to_end(key)
        while len(_owners) > _MAX_PANELS:
            _owners.popitem(last=False)


def release(message: Message | None) -> None:
    """Забыть панель (например, перед её пересозданием)."""
    if is_group(message):
        _owners.pop((message.chat.id, message.message_id), None)


def owner_of(chat_id: int, message_id: int) -> int | None:
    key = (chat_id, message_id)
    owner = _owners.get(key)
    if owner is not None:
        _owners.move_to_end(key)  # активная панель не вытесняется
    return owner
