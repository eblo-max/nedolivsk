"""Разовый тест: шлёт в указанный чат все анимэффекты сообщений.

Запуск:  python scripts/test_effects.py <chat_id>
Эффекты видны ТОЛЬКО в личке (приватный чат). С поллингом задеплоенного
бота не конфликтует — это одиночные send_message без getUpdates.
"""

import asyncio
import sys

from aiogram import Bot

from bot import effects
from bot.config import settings

FX = [
    ("🎉 Конфетти (FX_PARTY) — победа в бою", effects.FX_PARTY),
    ("💩 Какашка (FX_POOP) — поражение в бою", effects.FX_POOP),
    ("🔥 Огонь (FX_FIRE)", effects.FX_FIRE),
    ("❤️ Сердце (FX_HEART)", effects.FX_HEART),
    ("👍 Лайк (FX_LIKE)", effects.FX_LIKE),
    ("👎 Дизлайк (FX_DISLIKE)", effects.FX_DISLIKE),
]


async def main(chat_id: int) -> None:
    bot = Bot(token=settings.bot_token)
    try:
        for text, fx in FX:
            await bot.send_message(chat_id, text, message_effect_id=fx)
            await asyncio.sleep(1.2)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/test_effects.py <chat_id>")
    asyncio.run(main(int(sys.argv[1])))
