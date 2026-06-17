"""Зазывала (рефералка): личная ссылка, прогресс и топ зазывал."""

from urllib.parse import quote

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()

_SHARE_TEXT = "Айда в Недоливск — заведём кабаки и зальём весь город элем! 🍺"


async def _show(callback: CallbackQuery, text: str, markup) -> None:
    """Показ на месте, на картинке зазывалы — без новых «устаревающих» окон."""
    await common.show_image_panel(
        callback.message, images.named_image("priglashenie"),
        text, markup, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if player is None or not player.tavern:
        await callback.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{player.id}"
    invited = await repo.count_referrals(session, player.id)
    share = f"https://t.me/share/url?url={quote(link)}&text={quote(_SHARE_TEXT)}"
    await _show(callback, texts.referral_screen(link, invited, player.ref_tier),
                kb.referral_kb(share))


@router.callback_query(F.data == "referrers")
async def cb_referrers(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = await repo.top_referrers(session)
    await _show(callback, texts.referrers_screen(rows, callback.from_user.id),
                kb.referrers_kb())
