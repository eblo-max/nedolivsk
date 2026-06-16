"""Рейд-босс: регистрация (фаза сбора) и битва (бьют только записавшиеся).

Анонс в чате — ВИДЕО-ролик босса (assets/<boss_key>.mp4) с подписью, которая
обновляется весь цикл: отсчёт сбора → HP-бар битвы → экран смерти/ухода. Если
ролика нет — обычный текст (фолбэк). HP босса — единый в БД. По клику обновляем
сообщение ТОГО чата, где нажали; отсчёт и общий HP синхронит нотифаер (раз в тик).
Кнопки публичные — PanelGuard пропускает raidjoin/raidhit/raidref (см. middlewares).
"""

from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import images, texts
from bot.db import repo
from bot.game import inventory, items, raid
from bot.handlers import common
from bot.keyboards.inline import raid_gather_kb, raid_kb
from bot.sender import deliver

router = Router()


def raid_video(boss_key: str):
    """Путь к ролику босса (assets/<video>.mp4) или None, если ролика нет."""
    spec = raid.BOSSES.get(boss_key)
    return images.named_video(spec.video) if (spec and spec.video) else None


async def send_raid_announce(bot: Bot, chat_id: int, boss, caption: str, markup):
    """Анонс босса: видео-ролик с подписью (file_id кэшируется — грузим 1 раз),
    либо текст, если ролика нет. Возвращает Message|None."""
    path = raid_video(boss.boss_key)
    if path is not None:
        sent = await bot.send_video(
            chat_id, common.cached_media(path), caption=caption, reply_markup=markup)
        common.remember_file_id(path, sent)   # дальше по чатам — по file_id
        return sent
    return await bot.send_message(chat_id, caption, reply_markup=markup)


async def edit_raid_announce(bot: Bot, chat_id: int, msg_id: int, is_video: bool,
                             caption: str, markup):
    """Правка анонса: видео → подпись, текст → текст (markup=None убирает кнопки)."""
    if is_video:
        return await bot.edit_message_caption(
            chat_id=chat_id, message_id=msg_id, caption=caption, reply_markup=markup)
    return await bot.edit_message_text(
        caption, chat_id=chat_id, message_id=msg_id, reply_markup=markup)


async def _render(cb: CallbackQuery, boss) -> None:
    """Перерисовать сообщение под текущую фазу (подпись видео либо текст)."""
    if boss.status == "gathering":
        text, markup = texts.raid_gather_screen(boss), raid_gather_kb(boss.id)
    else:
        text, markup = texts.raid_screen(boss), raid_kb(boss.id)
    msg: Message = cb.message
    try:
        if msg.video:
            await msg.edit_caption(caption=text, reply_markup=markup)
        else:
            await msg.edit_text(text, reply_markup=markup)
    except Exception:  # noqa: BLE001 — перерисовка косметическая, не должна ронять хендлер
        pass


async def _safe_answer(cb: CallbackQuery, text: str = "", *, alert: bool = False) -> None:
    """Ответ на колбэк, который НЕ должен откатывать транзакцию (query too old / 429)."""
    try:
        await cb.answer(text, show_alert=alert)
    except Exception:  # noqa: BLE001
        pass


def _drop_apply(winner, drop: dict | None) -> str:
    if drop is None:
        return ""
    if drop["kind"] == "gold":
        winner.gold += drop["qty"]
        return f"{drop['qty']} 🪙"
    if drop["kind"] == "res":
        inventory.add(winner, drop["res"], drop["qty"])
        from bot.game import balance
        return f"{balance.RESOURCE_NAMES.get(drop['res'], drop['res'])} ×{drop['qty']}"
    if drop["kind"] == "gear":
        item = items.CATALOG.get(drop["item_id"])
        if item is None:
            return ""
        tier = int(drop.get("tier", 1))
        stars = items.TIER_STARS.get(tier, "★")
        eq = dict(winner.equipment or {})
        if item.slot not in eq:
            eq[item.slot] = items.make_entry(item.id, tier)
            winner.equipment = eq
            return f"🛡 снаряга «{item.name}» {stars} (надета!)"
        # слот занят — компенсация слитками тем щедрее, чем выше ярус
        comp = 15 * tier
        inventory.add(winner, "ingot", comp)
        return f"слитки ×{comp} (на «{item.name}» {stars} уже есть снаряга)"
    return ""


@router.callback_query(F.data == "raidopen")
async def cb_raid_open(cb: CallbackQuery, session: AsyncSession) -> None:
    """Открыть экран рейда из меню (личечные игроки): свежий панель-ролик по тапу."""
    boss = await repo.get_active_raid(session)
    if boss is None:
        await cb.answer("Рейд уже закончился — в другой раз!", show_alert=True)
        return
    if boss.status == "gathering":
        caption, markup = texts.raid_gather_screen(boss), raid_gather_kb(boss.id)
    else:
        caption, markup = texts.raid_screen(boss), raid_kb(boss.id)
    await send_raid_announce(cb.bot, cb.message.chat.id, boss, caption, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("raidref:"))
async def cb_raid_refresh(cb: CallbackQuery, session: AsyncSession) -> None:
    boss = await repo.get_raid(session, int(cb.data.split(":", 1)[1]))
    if boss is None or boss.status not in ("gathering", "active"):
        await cb.answer("Босса уже нет.", show_alert=True)
        return
    await _render(cb, boss)
    await cb.answer()


@router.callback_query(F.data.startswith("raidjoin:"))
async def cb_raid_join(cb: CallbackQuery, session: AsyncSession) -> None:
    player = await repo.get_player(session, cb.from_user.id)
    if player is None or not player.tavern:
        await cb.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    boss = await repo.get_raid(session, int(cb.data.split(":", 1)[1]), lock=True)
    if boss is None or boss.status != "gathering":
        await cb.answer("Сбор уже закончился.", show_alert=True)
        return
    if not raid.register(boss, player):
        await cb.answer("Ты уже записан — жди начала битвы!", show_alert=True)
        return
    repo.add_log(session, "player", player.id, "⚔️ записался в рейд")
    await session.commit()  # фиксируем запись ДО косметики (сбой UI не откатит)
    await _render(cb, boss)
    await _safe_answer(cb, "Ты в рейде! Как босс дойдёт — врежем все вместе.", alert=True)


@router.callback_query(F.data.startswith("raidhit:"))
async def cb_raid_hit(cb: CallbackQuery, session: AsyncSession) -> None:
    # Босса лочим ПЕРВЫМ (единый порядок локов во всех путях рейда), затем игрока —
    # иначе встречные удары и kill-path (он лочит участников под локом босса) дают
    # цикл «держу игрока, жду босса / держу босса, жду игрока» → дедлок в Postgres.
    boss = await repo.get_raid(session, int(cb.data.split(":", 1)[1]), lock=True)
    if boss is None or boss.status == "dead":
        await cb.answer("Босс уже повержен.", show_alert=True)
        return
    if boss.status == "gathering":
        await cb.answer("Бой ещё не начался — жди, идёт сбор.", show_alert=True)
        return
    if boss.status != "active":
        await cb.answer("Босс ушёл.", show_alert=True)
        return
    player = await repo.get_player(session, cb.from_user.id, for_update=True)
    if player is None or not player.tavern:
        await cb.answer("Сначала заведи кабак: /start", show_alert=True)
        return
    if not raid.is_registered(boss, player.id):
        await cb.answer("Ты не записался на этот рейд — в следующий раз успей в сбор.",
                        show_alert=True)
        return

    now = datetime.now(timezone.utc)
    left = raid.cooldown_left(boss, player.id, now)
    if left > 0:
        await cb.answer(f"Переведи дух — удар через {left // 60 + 1} мин.", show_alert=True)
        return

    raw, crit = raid.player_damage(player)
    dmg = raid.mitigate(boss.boss_key, raw)   # «толща» босса гасит часть урона
    raid.apply_hit(boss, player, dmg, now)
    repo.add_log(session, "player", player.id, f"⚔️ рейд: −{dmg} HP боссу")

    if not raid.is_dead(boss):
        # ФИКСИРУЕМ урон в БД ДО косметической отрисовки — иначе сбой правки
        # сообщения/ответа (429, «query too old») откатил бы записанный удар.
        await session.commit()
        await _render(cb, boss)
        await _safe_answer(
            cb, texts.raid_hit_toast(dmg, crit, boss.hp, boss.max_hp, soaked=raw - dmg))
        return

    # ── Босс повержен: раздаём награду ──
    boss.status = "dead"
    plan = raid.settle(boss)
    for pid, gold in plan["gold"].items():
        p = await repo.get_player(session, pid, for_update=True)
        if p is not None:
            p.gold += gold
            repo.queue_notify(session, pid,
                              f"⚔️ Босс повержен! Твоя доля добычи: +{gold} 🪙")
    drop_line, winner_name = "", None
    if plan["winner"] is not None:
        winner = await repo.get_player(session, plan["winner"], for_update=True)
        if winner is not None:
            winner_name = winner.first_name or str(winner.id)
            got = _drop_apply(winner, plan["drop"])
            if got:
                rarity = raid.RARITY.get((plan["drop"] or {}).get("rarity"), "")
                drop_line = f"{rarity} — {got}" if rarity else got
                repo.queue_notify(session, winner.id,
                                  f"🎁 С босса тебе выпал {rarity} трофей: {got}")
    # В список «кто рубился» — только реально бившие (dmg>0). Записавшиеся, но не
    # ударившие, награды не получают и в списке не маячат нулями.
    top = sorted(((r.get("name", str(p)), r.get("dmg", 0))
                  for p, r in (boss.contributions or {}).items()
                  if r.get("dmg", 0) > 0),
                 key=lambda x: -x[1])
    text = texts.raid_dead(boss, top, winner_name, drop_line)
    msgs = dict(boss.messages or {})
    if str(cb.message.chat.id) not in msgs:       # на всякий — и кликнутое сообщение
        msgs[str(cb.message.chat.id)] = cb.message.message_id
    is_video = raid_video(boss.boss_key) is not None
    # Фиксируем награды и ОТПУСКАЕМ локи (босс/игроки) ДО сетевых правок в Telegram —
    # иначе чужие клики «Бить» ждут весь цикл рассылки (как в hunt.py перед анимацией).
    await session.commit()
    raid.set_active(None)  # босс мёртв — убрать кнопку «Рейд-босс» из меню
    await _safe_answer(cb, "💀 БОСС ПОВЕРЖЕН!", alert=True)
    # Правим анонс во ВСЕХ чатах, где висел босс: экран победы, кнопки убираем
    # (иначе в других чатах осталась бы живая «Бить» по мёртвому боссу). Без спама
    # в посторонние чаты — только туда, где он реально появлялся.
    for cid_s, mid in msgs.items():
        await deliver(
            lambda c=int(cid_s), m=mid: edit_raid_announce(
                cb.bot, c, m, is_video, text, None),
            what=f"raid-dead→{cid_s}")
