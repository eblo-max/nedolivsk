"""Лавка скупщика: покупка сырья за золото (сток золота + разблокировка прогресса).

Покупка/докуп — под локом строки игрока: золото и лимит считаются без гонок.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.game import balance, economy, inventory, logic, shop
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()


async def _show(callback: CallbackQuery, text: str, markup) -> None:
    """Лавка скупщика на месте, на картинке купца (а не складской — заходят-то
    со склада). show_image_panel сам подменит фон и отступит к тексту, если файла нет."""
    await common.show_image_panel(
        callback.message, images.named_image("kypec"),
        text, markup, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, callback.from_user.id)
    if player is None or not player.tavern:
        await callback.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    await _show(callback, texts.shop_screen(player), kb.shop_kb(player))


@router.callback_query(F.data.startswith("shopbuy:"))
async def cb_shop_resource(callback: CallbackQuery, session: AsyncSession) -> None:
    res = callback.data.split(":", 1)[1]
    player = await repo.get_player(session, callback.from_user.id)
    if player is None or not player.tavern:
        await callback.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    if res not in shop.sellable():
        await callback.answer("Такого тут не торгуют.", show_alert=True)
        return
    if shop.max_affordable(player, res) <= 0:
        await callback.answer(texts.shop_cant_afford(res), show_alert=True)
        return
    await _show(callback, texts.shop_resource(player, res),
                kb.shop_resource_kb(res, player))


@router.callback_query(F.data.startswith("shopq:"))
async def cb_shop_buy(callback: CallbackQuery, session: AsyncSession) -> None:
    _, res, qty_s = callback.data.split(":")
    player = await repo.get_player(session, callback.from_user.id, for_update=True)
    if player is None or not player.tavern:
        await callback.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    qty = min(int(qty_s), shop.max_affordable(player, res))  # пере-clamp под золото/лимит
    if qty <= 0:
        await callback.answer(texts.shop_cant_afford(res), show_alert=True)
        return
    cost = qty * shop.price_for(player, res)
    player.gold -= cost
    economy.record(player, "shop", -cost)
    inventory.add(player, res, qty)
    shop.record_buy(player, res, qty)
    repo.add_log(session, "player", player.id,
                 f"🛒 купил в лавке {qty}×{balance.RESOURCE_NAMES.get(res, res)}")
    await _show(callback, texts.shop_bought(player, res, qty, cost),
                kb.shop_resource_kb(res, player))


@router.callback_query(F.data == "shopfill")
async def cb_shop_fill(callback: CallbackQuery, session: AsyncSession) -> None:
    """Докупить ровно недостающее сырьё под апгрейд и сразу улучшить — за один тап."""
    player = await repo.get_player(session, callback.from_user.id, for_update=True)
    if player is None or not player.tavern:
        await callback.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    tavern = player.tavern
    if tavern.level >= balance.MAX_LEVEL:
        await callback.answer(texts.UPGRADE_MAX, show_alert=True)
        return
    cost = balance.upgrade_cost(tavern.level)
    short = shop.shortfall(player.inventory, cost)
    if not short:   # сырья хватает — значит уперлись в золото, лавка тут не поможет
        await callback.answer(
            "Лавка торгует сырьём, не золотом — на сам апгрейд золота не хватает.",
            show_alert=True)
        return
    if any(q > shop.buy_room(player, r) for r, q in short.items()):
        await callback.answer(
            "Дневной лимит лавки не даёт добрать всё разом — возьми частями "
            "или дождись бригад.", show_alert=True)
        return
    need_gold = shop.bill(short) + cost.get("gold", 0)
    if player.gold < need_gold:
        await _show(callback, texts.shop_fill_poor(need_gold, player.gold), kb.back_kb())
        return
    spent = 0
    for r, q in short.items():
        player.gold -= shop.price_for(player, r) * q
        spent += shop.price_for(player, r) * q
        inventory.add(player, r, q)
        shop.record_buy(player, r, q)
    economy.record(player, "shop", -spent)
    result = logic.try_upgrade(player, tavern)
    if not result.ok:   # перестраховка — не должно случиться после докупа
        await callback.answer("Что-то не сошлось — попробуй «Улучшить» вручную.",
                              show_alert=True)
        return
    repo.add_log(session, "player", player.id,
                 f"🛒🔨 докупил сырьё ({spent}🪙) и улучшил таверну до ур.{result.new_level}")
    await _show(callback, texts.shop_fill_done(spent, result.new_level), kb.back_kb())
