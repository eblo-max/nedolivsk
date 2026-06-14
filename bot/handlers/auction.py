"""Аукцион: выставление лота и просмотр торгов (асинхронный сбыт)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import auction, balance
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


async def _player(callback: CallbackQuery, session: AsyncSession, *, lock: bool = False):
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


async def _city(callback: CallbackQuery, session: AsyncSession, player: Player):
    chat_id = callback.message.chat.id if panels.is_group(callback.message) \
        else player.chat_id
    return (await repo.get_or_create_city(session, chat_id)
            if chat_id is not None else None)


@router.callback_query(F.data == "auction")
async def cb_auction(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    city = await _city(callback, session, player)
    await common.show_image_panel(
        callback.message, images.named_image("auction"),
        texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern), callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "auc_new")
async def cb_auc_new(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    if player.tavern.auction:
        await callback.answer("Лот уже на торгах — дождись конца или сними.",
                              show_alert=True)
        return
    if not auction.sellable_goods(player.tavern):
        await callback.answer("В погребе пусто — нечего выставлять.", show_alert=True)
        return
    await common.caption_edit(
        callback.message, "🔨 <b>ЧТО ВЫСТАВИМ?</b>\n\nВыбери товар из погреба:",
        kb.auction_goods_kb(player.tavern))
    await callback.answer()


@router.callback_query(F.data.startswith("aucg:"))
async def cb_auc_good(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    good = callback.data.split(":", 1)[1]
    stock = int((player.tavern.products or {}).get(good, 0))
    if stock <= 0:
        await callback.answer("Этого товара уже нет.", show_alert=True)
        return
    city = await _city(callback, session, player)
    await common.caption_edit(
        callback.message, texts.auction_pick_qty(good, stock, city),
        kb.auction_qty_kb(good, stock))
    await callback.answer()


@router.callback_query(F.data.startswith("aucq:"))
async def cb_auc_qty(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    _, good, qty_s = callback.data.split(":")
    qty = int(qty_s)
    city = await _city(callback, session, player)
    fv = auction.fair_value(city, good)
    prices = [max(1, round(fv * t)) for t in balance.AUCTION_PRICE_TIERS]
    await common.caption_edit(
        callback.message, texts.auction_pick_price(good, qty, city),
        kb.auction_price_kb(good, qty, prices))
    await callback.answer()


@router.callback_query(F.data.startswith("aucp:"))
async def cb_auc_price(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    _, good, qty_s, idx_s = callback.data.split(":")
    qty, idx = int(qty_s), int(idx_s)
    city = await _city(callback, session, player)
    fv = auction.fair_value(city, good)
    prices = [max(1, round(fv * t)) for t in balance.AUCTION_PRICE_TIERS]
    if not 0 <= idx < len(prices):
        await callback.answer()
        return
    ok, reason = auction.create(player, player.tavern, good, qty, prices[idx])
    if not ok:
        msg = {"busy": "Лот уже на торгах.", "empty": "Товара нет.",
               "price": "Неверная цена."}.get(reason, "Не вышло выставить.")
        await callback.answer(msg, show_alert=True)
        return
    await common.caption_edit(
        callback.message, texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern))
    await callback.answer("Лот выставлен — жди покупателей!")


@router.callback_query(F.data == "auc_cancel")
async def cb_auc_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    lot = player.tavern.auction or None
    if lot and lot.get("top_bid"):
        # есть ставка — предупреждаем, что упустит куш (но позволяем)
        pass
    if not auction.cancel(player, player.tavern):
        await callback.answer("Активных торгов нет.", show_alert=True)
        return
    city = await _city(callback, session, player)
    await common.caption_edit(
        callback.message, texts.auction_screen(player.tavern, city),
        kb.auction_kb(player.tavern))
    await callback.answer("Лот снят, товар вернулся в погреб.")
