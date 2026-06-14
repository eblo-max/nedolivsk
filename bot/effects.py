"""Анимированные эффекты сообщений и реакции бота на посты в чате (Bot API 7.3+).

Эффекты (`message_effect_id`) Telegram показывает ТОЛЬКО в приватных чатах —
в группах параметр отклоняется, поэтому подставляем его лишь в личке.
Реакции (`setMessageReaction`) работают в любых чатах: бот ставит «бейдж»
на своё сообщение, чтобы оживить ленту общего чата.
"""

import logging

from aiogram import Bot
from aiogram.types import Chat, Message, ReactionTypeEmoji

logger = logging.getLogger(__name__)

# Публичные id анимаций (см. https://gist.github.com/wiz0u/2a6d40c8f635687be363d72251a264da)
FX_FIRE = "5104841245755180586"     # 🔥
FX_LIKE = "5107584321108051014"     # 👍
FX_DISLIKE = "5104858069142078462"  # 👎
FX_HEART = "5159385139981059251"    # ❤️
FX_PARTY = "5046509860389126442"    # 🎉
FX_POOP = "5046589136895476101"     # 💩


def for_private(chat: Chat | None, effect_id: str) -> str | None:
    """Эффект допустим только в личке; в группе вернём None (Telegram отклонит)."""
    return effect_id if chat is not None and chat.type == "private" else None


async def react(bot: Bot, chat_id: int, message_id: int, emoji: str,
                big: bool = False) -> None:
    """Поставить боту реакцию на сообщение. Сбои глотаем (нет прав/чат недоступен)."""
    try:
        await bot.set_message_reaction(
            chat_id, message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)], is_big=big)
    except Exception:  # noqa: BLE001 — реакции не критичны
        logger.debug("Реакция %s не поставлена в чат %s", emoji, chat_id)


async def react_msg(msg: Message | None, emoji: str, big: bool = False) -> None:
    """То же, но по объекту сообщения (бот берём из самого msg)."""
    if msg is None:
        return
    await react(msg.bot, msg.chat.id, msg.message_id, emoji, big)
