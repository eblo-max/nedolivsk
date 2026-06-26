"""Охота: бестиарий, бриф зверя (расклад по статам + добыча), бой.

У зверя может быть видео (assets/<video>.mp4) — показываем его при просмотре
брифа и в бою, морфя панель в видео; в меню/прочих экранах — фото/текст.
"""

import asyncio

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaVideo
from sqlalchemy.ext.asyncio import AsyncSession

from bot import effects, images, panels, texts
from bot.db import repo
from bot.db.models import Player
from bot.game import combat
from bot.handlers import common
from bot.keyboards import inline as kb

router = Router()

# Временно закрыто: охота на доработке (перенос в мини-апп / анимир. бой).
_HUNT_WIP = "🏹 Охота сейчас на доработке — скоро откроем! Загляни позже."


async def _player(
    callback: CallbackQuery, session: AsyncSession, *, lock: bool = False
) -> Player | None:
    player = await repo.get_player(session, callback.from_user.id, for_update=lock)
    if not player or not player.tavern:
        await callback.answer("Сначала обзаведись кабаком: /start", show_alert=True)
        return None
    return player


async def _render(callback: CallbackQuery, caption: str, markup,
                  video: str | None = None, image: str = "oxota") -> None:
    """Показать экран охоты. video задан → панель-видео (морфим); иначе статичная
    картинка image (по умолчанию «oxota»; экран лечения шлёт «sklad» — погреб)."""
    msg = callback.message
    path = images.named_video(video) if video else None
    if path is not None:
        media = common.cached_media(path)
        if msg.photo or msg.video:           # есть медиа — подменяем на видео
            try:
                res = await msg.edit_media(
                    InputMediaVideo(media=media, caption=caption, parse_mode="HTML"),
                    reply_markup=markup)
                common.remember_file_id(path, res)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return                   # уже показано — не дёргаем панель
                # иначе сообщение не редактируется (старое и т.п.) — пересоздаём
        panels.release(msg)                  # из текста / правка не прошла — пересоздаём
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass
        sent = await msg.answer_video(media, caption=caption, reply_markup=markup)
        common.remember_file_id(path, sent)
        panels.claim(sent, callback.from_user.id)
        return
    # нет видео — статичная картинка экрана (с видео уходим сюда же:
    # show_image_panel сам пересоздаст панель из видео в фото).
    await common.show_image_panel(
        msg, images.named_image(image), caption, markup, callback.from_user.id)


@router.callback_query(F.data == "hunt")
async def cb_hunt(callback: CallbackQuery, session: AsyncSession) -> None:
    # ВРЕМЕННО ЗАКРЫТО — охота на доработке.
    await callback.answer(_HUNT_WIP, show_alert=True)


@router.callback_query(F.data.startswith("hbeast:"))
async def cb_hunt_beast(callback: CallbackQuery, session: AsyncSession) -> None:
    """Бриф зверя: HP, расклад по статам, таблица добычи (+ видео, если есть)."""
    await callback.answer(_HUNT_WIP, show_alert=True)   # ВРЕМЕННО ЗАКРЫТО
    return
    player = await _player(callback, session)
    if player is None:
        return
    enemy = combat.ENEMY.get(callback.data.split(":", 1)[1])
    if enemy is None or (enemy.region and enemy.region != player.region):
        await callback.answer("Этот зверь водится не в твоём краю.", show_alert=True)
        return
    await _render(callback, texts.hunt_detail(player, enemy),
                  kb.hunt_detail_kb(enemy.id), video=enemy.video or None)
    await callback.answer()


@router.callback_query(F.data == "healmenu")
async def cb_heal_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session)
    if player is None:
        return
    await _render(callback, texts.heal_menu(player), kb.heal_kb(player), image="sklad")
    await callback.answer()


@router.callback_query(F.data.startswith("heal:"))
async def cb_heal_do(callback: CallbackQuery, session: AsyncSession) -> None:
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    res = combat.heal(player, callback.data.split(":", 1)[1])
    if res is None:
        await callback.answer("Нечем подлечиться или уже сыт.", show_alert=True)
        return
    await _render(callback, texts.heal_menu(player), kb.heal_kb(player), image="sklad")
    await callback.answer(f"+{res['healed']} ❤")


async def _set_caption(msg, text: str, markup) -> None:
    """Правит подпись/текст текущей панели (видео/фото/текст) — для анимации."""
    try:
        if msg.photo or msg.video:
            await msg.edit_caption(caption=text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("hfight:"))
async def cb_hunt_fight(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer(_HUNT_WIP, show_alert=True)   # ВРЕМЕННО ЗАКРЫТО
    return
    player = await _player(callback, session, lock=True)
    if player is None:
        return
    enemy_id = callback.data.split(":", 1)[1]
    _e = combat.ENEMY.get(enemy_id)
    if _e is not None and _e.region and _e.region != player.region:
        await callback.answer("Этот зверь водится не в твоём краю.", show_alert=True)
        return
    res = combat.hunt(player, enemy_id)
    if not res.ok:
        if res.reason == "lowhp":
            await callback.answer(
                f"Слишком ранен — отлёживайся, в строй через {res.minutes_left} мин.",
                show_alert=True)
        else:
            await callback.answer()
        return
    if res.fight.win:
        g = (res.loot or {}).get("gold", 0)
        repo.add_log(session, "player", player.id,
                     f"🏹 одолел: {res.enemy.name} (+{g} 🪙)")
    else:
        repo.add_log(session, "player", player.id,
                     f"🩸 проиграл: {res.enemy.name} (−{res.gold_lost} 🪙)")
    await session.commit()  # фиксируем бой и отпускаем лок до анимации (~5с)
    await callback.answer("🏹 Победа!" if res.fight.win else "🩸 Поражение…")
    # Анимация боя: раунды раскрываются по кадрам, последний — итог с кнопками.
    frames = texts.hunt_anim_frames(res)
    for fr in frames[:-1]:
        await _set_caption(callback.message, fr, None)
        await asyncio.sleep(0.9)
    await _finish(callback, frames[-1], res.fight.win)


async def _finish(callback: CallbackQuery, text: str, win: bool) -> None:
    """Итог боя. В личке — свежая карточка с анимэффектом (🎉/💩); в группе
    эффекты недоступны, потому правим панель на месте."""
    msg = callback.message
    markup = kb.hunt_after_kb()
    fx = effects.for_private(msg.chat, effects.FX_PARTY if win else effects.FX_POOP)
    if fx is None:
        await _set_caption(msg, text, markup)
        return
    panels.release(msg)
    try:
        await msg.delete()  # гасим видео-панель, чтобы итог «выстрелил» эффектом
    except TelegramBadRequest:
        pass
    sent = await msg.answer(text, reply_markup=markup, message_effect_id=fx)
    panels.claim(sent, callback.from_user.id)
