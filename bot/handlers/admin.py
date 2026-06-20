"""Админ-команды. Работают только для ADMIN_ID из настроек."""

from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import announce, texts
from bot.config import settings
from bot.db import repo
from bot.db.models import Player, Tavern
from bot.game import balance, invasion
from bot.game import world as wld
from bot.keyboards.inline import invasion_announce_kb
from bot.sender import deliver

router = Router()


def _is_admin(message: Message) -> bool:
    return settings.admin_id != 0 and message.from_user.id == settings.admin_id


@router.message(Command("orc"))
async def cmd_orc(message: Message, command: CommandObject, session: AsyncSession) -> None:
    """Запустить ивент «Орда орков». /orc — обычный; /orc fast — быстрый тест-режим."""
    if not _is_admin(message):
        return
    if await repo.get_active_invasion(session) is not None:
        await message.answer("Орда уже идёт — дождись итога текущего ивента.")
        return
    fast = bool(command.args and command.args.strip().lower() == "fast")
    now = datetime.now(timezone.utc)
    total = await repo.world_might_sum(session)
    threshold = invasion.horde_threshold(total)
    g_until, r_at = invasion.schedule(now, fast=fast)
    inv = repo.create_invasion(session, sprite=invasion.SPRITE, threshold=threshold,
                               gather_until=g_until, resolve_at=r_at)
    world = await repo.get_or_create_world(session)
    world.invasion_next_at = None          # активна — авто не спавнит поверх
    await session.flush()                  # нужен inv.id для кнопок
    repo.add_log(session, "admin", message.from_user.id,
                 f"🪓 запущена Орда орков (порог {threshold}, сбор {invasion.GATHER_MINUTES} мин)")

    if invasion.TEST_MODE:                  # тест: без анонсов в чаты/лички — только админу
        from bot.webapp import base_url
        from bot.keyboards.inline import invasion_map_dm_kb
        b = base_url()
        kb = invasion_map_dm_kb(b + "/map") if b else None
        timing = (f"⚡ быстрый режим: сбор {invasion.FAST_GATHER_SECONDS}с, "
                  f"бой ~{invasion.FAST_MARCH_SECONDS + invasion.FAST_BATTLE_SECONDS}с" if fast
                  else f"сбор {invasion.GATHER_MINUTES} мин, бой ~{invasion.BATTLE_SECONDS // 60} мин")
        await message.answer(
            f"🪓 <b>Орда запущена в ТЕСТ-режиме</b> (без анонсов в чаты/лички).\n"
            f"Порог {threshold} (мощь города {total}). {timing}. "
            "Открой карту — записывайся и тестируй:",
            reply_markup=kb)
        return

    from bot.handlers.invasion import send_invasion_announce
    caption = texts.invasion_gather_screen(inv)
    chat_ids = await repo.all_chat_ids(session)
    msgs: dict[str, int] = {}
    for cid in chat_ids:
        sent = await deliver(lambda c=cid: send_invasion_announce(
            message.bot, c, caption, invasion_announce_kb(inv.id)), what=f"orc→{cid}")
        if sent is not None:
            msgs[str(cid)] = sent.message_id
    inv.messages = msgs
    cut = now - timedelta(days=7)
    pids = [r[0] for r in (await session.execute(
        select(Player.id).where(Player.last_seen_at >= cut))).all()]
    for uid in pids:
        repo.queue_notify(session, uid, texts.invasion_push_dm(inv))
    await message.answer(
        f"🪓 Орда орков запущена! Порог орды: <b>{threshold}</b> "
        f"(мощь города {total}). Сбор {invasion.GATHER_MINUTES} мин. "
        f"В чаты: {len(msgs)}/{len(chat_ids)}. Пуш в личку: {len(pids)}.")


@router.message(Command("reset"))
async def cmd_reset(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    if not _is_admin(message):
        return  # молча игнорируем чужаков
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Так: /reset <telegram_id>")
        return

    target_id = int(command.args.strip())
    player = await session.get(Player, target_id)
    if player is None:
        await message.answer(f"Игрок {target_id} не найден. Некого сносить.")
        return

    await session.execute(delete(Tavern).where(Tavern.player_id == target_id))
    await repo.delete_player_orders(session, target_id)
    await session.execute(delete(Player).where(Player.id == target_id))
    await message.answer(
        f"🔥 Готово. Игрок {target_id} стёрт подчистую — таверна, золото, "
        "слот на карте. Пусть жмёт /start и начинает с нуля."
    )


@router.message(Command("fair"))
async def cmd_fair(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message):
        return
    world = await repo.get_or_create_world(session)
    wld.open_fair(world)
    await session.flush()  # зафиксировать состояние мира до рассылки
    chat_ids = await repo.all_chat_ids(session)
    await announce.broadcast_fair(message.bot, "open", chat_ids, world)
    await message.answer(
        f"🎪 Ярмарка открыта вручную на {balance.FAIR_DURATION_HOURS} ч. "
        f"Спрос ×{balance.FAIR_DEMAND_MULT:g}. Анонс ушёл в чаты: {len(chat_ids)}."
    )
