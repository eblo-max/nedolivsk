"""Подкидыш в чате: кто первый нажал «Поднять», тот и подобрал (атомарно).

Кнопка публичная — её жмёт не владелец панели, а любой в чате. PanelGuard
пропускает callback'и loot: без проверки владельца.
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot import effects, texts
from bot.db import repo
from bot.game import inventory, loot
from bot.keyboards import inline as kb

router = Router()


@router.callback_query(F.data.startswith("loot:"))
async def cb_loot(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        drop_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    won = await repo.claim_loot(session, drop_id, callback.from_user.id)
    if not won:
        await callback.answer("Поздно! Уже подобрали (или сгнило).", show_alert=True)
        return

    out = loot.roll()
    stored = True
    if out["kind"] == "resource":
        player = await repo.get_player(session, callback.from_user.id, for_update=True)
        if player is not None:
            inventory.add(player, out["res"], out["qty"])
        else:
            stored = False  # выиграл ресурс, но кабака нет — некуда деть

    name = callback.from_user.first_name or "Кто-то"
    if out["kind"] == "resource":
        from bot.game import balance
        what = f"{out['qty']}× {balance.RESOURCE_NAMES.get(out['res'], out['res'])}"
    elif out["kind"] == "nothing":
        what = "пшик"
    else:
        what = "хлам"
    repo.add_log(session, "player", callback.from_user.id, f"🤲 поднял подкидыш: {what}")
    try:  # подкидыш — текстовое сообщение бота, правим на месте
        await callback.message.edit_text(texts.loot_claimed(name, out, stored),
                                          reply_markup=None)
    except TelegramBadRequest:
        pass
    await effects.react_msg(callback.message, "🔥")  # 👀 → 🔥: добычу урвали

    if out["kind"] == "resource" and stored:
        await callback.answer(f"+{out['qty']} на склад!")
    elif out["kind"] == "nothing":
        await callback.answer("Пусто… не повезло.")
    else:
        await callback.answer("Фу, гадость.")
