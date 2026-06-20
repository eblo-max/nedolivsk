"""Ивент «Орда орков»: регистрация войска (фаза сбора).

Кнопка публичная (PanelGuard пропускает invjoin/invref — жмёт любой в чате).
Запись АТОМАРНАЯ (repo.invasion_register — jsonb-merge): только в фазе сбора,
без дублей, не затирает чужих. Анонс в чатах — текст; правит нотифаер (отсчёт
сбора → битва → итог). Спавн и резолв — в админ-команде и нотифаере.
"""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db import repo
from bot.game import combat, invasion, worldmap
from bot.keyboards.inline import invasion_gather_kb

router = Router()


async def send_invasion_announce(bot: Bot, chat_id: int, caption: str, markup):
    return await bot.send_message(chat_id, caption, reply_markup=markup)


async def edit_invasion_announce(bot: Bot, chat_id: int, msg_id: int, caption: str, markup):
    try:
        return await bot.edit_message_text(
            caption, chat_id=chat_id, message_id=msg_id, reply_markup=markup)
    except TelegramBadRequest:
        return None


def _tavern_pos(player) -> tuple[float, float]:
    """Нормированная позиция таверны на карте (как в webapp): слот или регион."""
    tav = player.tavern
    if tav is not None and tav.map_slot is not None:
        p = worldmap.slot_norm_pos(tav.map_slot)
        if p:
            return p
    return worldmap.region_point(player.region or "", player.id) or (0.5, 0.5)


@router.callback_query(F.data.startswith("invref:"))
async def cb_inv_refresh(cb: CallbackQuery, session: AsyncSession) -> None:
    inv = await repo.get_active_invasion(session)
    if inv is None or inv.status != "gathering":
        await cb.answer("Сбор уже закончился.", show_alert=True)
        return
    try:
        await cb.message.edit_text(texts.invasion_gather_screen(inv),
                                   reply_markup=invasion_gather_kb(inv.id))
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("invjoin:"))
async def cb_inv_join(cb: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, cb.from_user.id)
    if player is None or not player.tavern:
        await cb.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    inv = await repo.get_active_invasion(session)
    if inv is None or inv.status != "gathering":
        await cb.answer("Сбор уже закончился — войска выступили.", show_alert=True)
        return
    if invasion.is_registered(inv, player.id):
        await cb.answer("Войско уже выслано — жди битвы!", show_alert=True)
        return
    record = invasion.make_record(player, player.tavern, _tavern_pos(player),
                                  combat.player_stats(player))
    ok = await repo.invasion_register(session, inv.id, player.id, record)
    if not ok:
        await cb.answer("Войско уже выслано — жди битвы!", show_alert=True)
        return
    repo.add_log(session, "player", player.id, "⚔️ поднял войско на орду орков")
    await session.commit()
    # обновим экран сбора (свежий счётчик силы/таверн) тому, кто нажал
    fresh = await repo.get_active_invasion(session)
    if fresh is not None and cb.message is not None:
        try:
            await cb.message.edit_text(texts.invasion_gather_screen(fresh),
                                       reply_markup=invasion_gather_kb(fresh.id))
        except TelegramBadRequest:
            pass
    await cb.answer(
        f"⚔️ Дружина выслана! Сила войска: {record['might']}. "
        "Жди битвы — добыча по вкладу.", show_alert=True)
