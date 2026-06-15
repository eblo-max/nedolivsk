"""Анонсы мировых событий в общие чаты."""

from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import FSInputFile

from bot import images, texts
from bot.sender import deliver


async def broadcast_fair(
    bot: Bot, event: str, chat_ids: list[int], world
) -> None:
    """Рассылает анонс ярмарки во все известные чаты. Открытие — с картинкой,
    file_id переиспользуется между чатами (одна загрузка). Падение одного чата
    (бот выгнан и т.п.) не срывает рассылку в остальные."""
    now = datetime.now(timezone.utc)
    media = None
    if event == "pre":
        left = int((world.next_fair_at - now).total_seconds() // 60)
        text = texts.fair_pre_announce(max(1, left))
    elif event == "open":
        text = texts.fair_open_announce()
        img = images.named_image("yarmarka")
        media = FSInputFile(img) if img is not None else None
    elif event == "close":
        text = texts.fair_close_announce()
    else:
        return

    for chat_id in chat_ids:
        if media is not None:
            sent = await deliver(
                lambda cid=chat_id: bot.send_photo(cid, media, caption=text),
                what=f"ярмарка→{chat_id}")
            if sent is not None and sent.photo:
                media = sent.photo[-1].file_id  # дальше шлём по file_id
        else:
            await deliver(lambda cid=chat_id: bot.send_message(cid, text),
                          what=f"ярмарка→{chat_id}")
