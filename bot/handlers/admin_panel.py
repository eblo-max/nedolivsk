"""Фундаментальная админ-панель через бота (только для ADMIN_ID).

/admin — сводка мира, список игроков с пагинацией, карточка игрока со всеми
данными и полным управлением: золото/репутация/уровень/ресурсы/снаряга/здания/
кулдауны/бонус/god-режим/сброс/удаление. Точные значения — через ввод (FSM).
"""

from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.models import CityState, KnownChat, Player, Tavern
from bot.game import balance, buff, buildings, combat, items, production, season
from bot.game import world as wld

router = Router()

PAGE = 8


def _is_admin(uid: int) -> bool:
    return settings.admin_id != 0 and uid == settings.admin_id


async def _guard_cb(cb: CallbackQuery) -> bool:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Не для тебя.", show_alert=True)
        return False
    return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── ВВП и форматирование ───────────────────────────────────────────────────
def _gdp(player: Player, tavern: Tavern | None) -> int:
    if tavern is None:
        return player.gold
    g = balance.tavern_gdp(player.inventory, player.gold, tavern.level,
                           tavern.income_rate, tavern.reputation)
    g += items.gear_value(getattr(player, "equipment", None))
    g += buildings.invested_value(tavern)
    g += production.products_value(tavern)
    return int(g)


def _ago(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    sec = (_now() - dt).total_seconds()
    if sec < 0:
        return f"через {int(-sec // 60) + 1}м"
    if sec < 3600:
        return f"{int(sec // 60)}м назад"
    if sec < 86400:
        return f"{int(sec // 3600)}ч назад"
    return f"{int(sec // 86400)}д назад"


# ── Экран: сводка мира ─────────────────────────────────────────────────────
async def _world_summary(session: AsyncSession) -> str:
    total = await session.scalar(select(func.count(Player.id))) or 0
    taverns = await session.scalar(select(func.count(Tavern.id))) or 0
    gold_sum = await session.scalar(select(func.coalesce(func.sum(Player.gold), 0))) or 0
    chats = await session.scalar(select(func.count(KnownChat.chat_id))) or 0
    cities = await session.scalar(select(func.count(CityState.chat_id))) or 0
    # активные за сутки — по сбору дохода
    day = _now().timestamp() - 86400
    rows = await session.execute(select(Tavern.last_income_at))
    active = sum(1 for (t,) in rows if t and t.timestamp() >= day)

    fair = "🎪 идёт" if wld.is_fair() else "—"
    s = season.current()
    hol = season.holiday()
    season_s = f"{hol.emoji} {hol.name}" if hol else f"{s.emoji} {s.name}"

    return "\n".join([
        "🛠 <b>АДМИН-ПАНЕЛЬ НЕДОЛИВСКА</b>",
        "",
        f"👥 Игроков: <b>{total}</b> · 🏠 таверн: <b>{taverns}</b>",
        f"🟢 Активны за сутки: <b>{active}</b>",
        f"🪙 Золота в мире: <b>{gold_sum:,}</b>".replace(",", " "),
        f"💬 Чатов: <b>{chats}</b> · 🏙 городов: <b>{cities}</b>",
        f"🌍 Сезон: {season_s} · Ярмарка: {fair}",
        "",
        "<i>Выбери раздел.</i>",
    ])


def _home_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Игроки", callback_data="adm:list:0")
    kb.button(text="🔍 Найти игрока", callback_data="adm:find")
    kb.button(text="🌍 Мир и события", callback_data="adm:world")
    kb.button(text="🏙 Города/чаты", callback_data="adm:cities")
    kb.button(text="🔄 Обновить", callback_data="adm:home")
    kb.adjust(2, 2, 1)
    return kb


# ── Экран: список игроков ──────────────────────────────────────────────────
async def _players_page(session: AsyncSession, page: int):
    total = await session.scalar(select(func.count(Player.id))) or 0
    rows = (await session.execute(
        select(Player).order_by(Player.gold.desc())
        .limit(PAGE).offset(page * PAGE)
    )).scalars().all()
    return rows, total


def _list_text(rows, total: int, page: int) -> str:
    pages = max(1, (total + PAGE - 1) // PAGE)
    lines = [f"👥 <b>ИГРОКИ</b> ({total}) · стр. {page + 1}/{pages}", ""]
    for p in rows:
        tav = p.tavern
        lvl = tav.level if tav else 0
        name = escape(p.first_name or "—")
        un = f"@{p.username}" if p.username else f"id{p.id}"
        lines.append(f"• <b>{name}</b> {un} · ур.{lvl} · {p.gold:,}🪙".replace(",", " "))
    if not rows:
        lines.append("<i>пусто</i>")
    return "\n".join(lines)


def _list_kb(rows, total: int, page: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for p in rows:
        name = (p.first_name or str(p.id))[:18]
        kb.button(text=f"{name} · {p.gold}🪙", callback_data=f"adm:p:{p.id}")
    sizes = [1] * len(rows)
    nav = []
    if page > 0:
        kb.button(text="◀️", callback_data=f"adm:list:{page - 1}")
        nav.append(1)
    if (page + 1) * PAGE < total:
        kb.button(text="▶️", callback_data=f"adm:list:{page + 1}")
        nav.append(1)
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(*sizes, len(nav) if nav else 1, 1)
    return kb


# ── Экран: карточка игрока ─────────────────────────────────────────────────
def _card_text(player: Player) -> str:
    t = player.tavern
    inv = player.inventory or {}
    eq = player.equipment or {}
    ico = {**balance.RESOURCE_EMOJI, **balance.GOODS_EMOJI}

    head = [
        f"🧍 <b>{escape(player.first_name or '—')}</b> "
        f"{'@' + player.username if player.username else ''}",
        f"<code>{player.id}</code> · рег. {player.created_at.date() if player.created_at else '—'}"
        f" · {'🟢' if player.is_active else '🔴'}",
        f"🗺 {balance.REGIONS.get(player.region, player.region or '—')} · "
        f"💬 чат: {player.chat_id or '—'}",
        "",
        f"📈 Ур.<b>{player.level}</b> · 🪙<b>{player.gold:,}</b>".replace(",", " ")
        + f" · ⭐{player.reputation}",
    ]
    if t is None:
        return "\n".join(head + ["", "<i>Таверны нет (не прошёл /start).</i>"])

    head.append(f"🏠 <b>{escape(t.name)}</b> ур.{t.level} · 👥{t.capacity} "
                f"✨{t.comfort} · 💰{t.income_rate}/ч · ⭐{t.reputation}")
    head.append(f"💎 ВВП: <b>{_gdp(player, t):,}</b>".replace(",", " "))

    invs = " ".join(f"{ico.get(r, r)}{int(q)}" for r, q in inv.items() if q) or "пусто"
    prods = " ".join(f"{production.GOODS[k].emoji}{int(v)}"
                     for k, v in (t.products or {}).items()
                     if k in production.GOODS and v) or "пусто"
    blds = " ".join(buildings.CATALOG[b].emoji for b in (t.buildings or [])
                    if b in buildings.CATALOG) or "нет"
    gear = " ".join(
        f"{items.CATALOG[items.parse_entry(e)[0]].name}{items.TIER_STARS[items.parse_entry(e)[1]]}"
        for e in eq.values() if items.parse_entry(e)[0] in items.CATALOG) or "голый"

    # производство (активные партии)
    busy = []
    for b in (t.production or {}):
        st, m = production.state(t, b)
        if st != "none":
            busy.append(f"{buildings.CATALOG[b].emoji if b in buildings.CATALOG else b}"
                        f":{'✅' if st == 'ready' else str(m) + 'м'}")
    # охота / бафы
    hp = combat.current_hp(player)
    act = buff.active(player)
    boon = buff.offer(player)
    exps = player.expeditions or []

    story = player.story or {}
    fac = story.get("faction", {})
    fac_s = " ".join(f"{k}:{v}" for k, v in fac.items() if v) or "—"
    pend = story.get("pending")
    q = len(story.get("queue", []) or [])

    body = [
        "",
        f"📦 Склад: {invs}",
        f"🛢 Погреб: {prods}",
        f"🏗 Здания: {blds}",
        f"🎒 Снаряга: {gear}",
        f"⚙️ Производство: {' '.join(busy) if busy else '—'}",
        f"❤️ HP: {hp}/{combat.max_hp()} · охота: {_ago(player.hunt_ready_at) if player.hunt_ready_at else 'готов'}",
        f"🎁 Баф: {act.name if act else '—'} · бонус: {boon.name if boon else '—'}",
        f"⛏ Бригад в деле: {len(exps)} · "
        f"крафт: {'да' if player.craft_item else '—'} · "
        f"стройка: {'да' if player.build_item else '—'}",
        f"🏛 Фракции: {fac_s} · события: pending={'да' if pend else '—'} очередь={q}",
    ]
    return "\n".join(head + body)


def _card_kb(player: Player) -> InlineKeyboardBuilder:
    i = player.id
    kb = InlineKeyboardBuilder()
    kb.button(text="🪙 +1k", callback_data=f"adm:gold:{i}:1000")
    kb.button(text="🪙 +10k", callback_data=f"adm:gold:{i}:10000")
    kb.button(text="🪙 −1k", callback_data=f"adm:gold:{i}:-1000")
    kb.button(text="🪙 задать", callback_data=f"adm:set:{i}:gold")
    kb.button(text="⭐ +100", callback_data=f"adm:rep:{i}:100")
    kb.button(text="⭐ задать", callback_data=f"adm:set:{i}:rep")
    kb.button(text="📈 ур.+1", callback_data=f"adm:lvl:{i}:1")
    kb.button(text="📈 задать", callback_data=f"adm:set:{i}:level")
    kb.button(text="📦 +500 ресурсов", callback_data=f"adm:resall:{i}:500")
    kb.button(text="📦 задать ресурс", callback_data=f"adm:set:{i}:res")
    kb.button(text="❤️ Полный HP", callback_data=f"adm:heal:{i}")
    kb.button(text="⏱ Снять кулдауны", callback_data=f"adm:cool:{i}")
    kb.button(text="🎁 Выдать бонус", callback_data=f"adm:bonus:{i}")
    kb.button(text="🎒 Топ-снаряга", callback_data=f"adm:gear:{i}")
    kb.button(text="🏗 Достроить всё", callback_data=f"adm:build:{i}")
    kb.button(text="🦸 GOD-режим", callback_data=f"adm:god:{i}")
    kb.button(text="🔄 Сброс прогресса", callback_data=f"adm:reset:{i}")
    kb.button(text="🗑 Удалить", callback_data=f"adm:del:{i}")
    kb.button(text="↻ Обновить", callback_data=f"adm:p:{i}")
    kb.button(text="👥 К списку", callback_data="adm:list:0")
    kb.adjust(4, 2, 2, 2, 2, 2, 2, 2, 2)
    return kb


async def _show_card(cb: CallbackQuery, session: AsyncSession, pid: int) -> None:
    player = await session.get(Player, pid)
    if player is None:
        await cb.answer("Игрок не найден.", show_alert=True)
        return
    await _edit(cb, _card_text(player), _card_kb(player))


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardBuilder) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:  # noqa: BLE001 — то же сообщение / нельзя редактировать
        await cb.message.answer(text, reply_markup=kb.as_markup())


# ── Точка входа ────────────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(await _world_summary(session),
                         reply_markup=_home_kb().as_markup())


@router.callback_query(F.data == "adm:home")
async def cb_home(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    await _edit(cb, await _world_summary(session), _home_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:list:"))
async def cb_list(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    page = int(cb.data.rsplit(":", 1)[1])
    rows, total = await _players_page(session, page)
    await _edit(cb, _list_text(rows, total, page), _list_kb(rows, total, page))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:p:"))
async def cb_player(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    await _show_card(cb, session, int(cb.data.rsplit(":", 1)[1]))
    await cb.answer()


# ── Быстрые действия ───────────────────────────────────────────────────────
async def _get(session: AsyncSession, pid: int) -> Player | None:
    return await session.get(Player, pid, with_for_update=True)


def _sync_level(player: Player) -> None:
    """Пересчитать параметры таверны под уровень игрока."""
    t = player.tavern
    if t is None:
        return
    t.level = player.level
    st = balance.stats_for_level(t.level)
    t.capacity, t.comfort, t.income_rate = st["capacity"], st["comfort"], st["income_rate"]


@router.callback_query(F.data.startswith("adm:gold:"))
async def cb_gold(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    _, _, pid, delta = cb.data.split(":")
    player = await _get(session, int(pid))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    player.gold = max(0, player.gold + int(delta))
    await _show_card(cb, session, player.id)
    await cb.answer(f"🪙 {player.gold}")


@router.callback_query(F.data.startswith("adm:rep:"))
async def cb_rep(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    _, _, pid, delta = cb.data.split(":")
    player = await _get(session, int(pid))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    player.reputation = max(0, player.reputation + int(delta))
    if player.tavern:
        player.tavern.reputation = max(0, player.tavern.reputation + int(delta))
    await _show_card(cb, session, player.id)
    await cb.answer(f"⭐ {player.reputation}")


@router.callback_query(F.data.startswith("adm:lvl:"))
async def cb_lvl(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    _, _, pid, delta = cb.data.split(":")
    player = await _get(session, int(pid))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    player.level = max(1, min(balance.MAX_LEVEL, player.level + int(delta)))
    _sync_level(player)
    await _show_card(cb, session, player.id)
    await cb.answer(f"📈 ур.{player.level}")


@router.callback_query(F.data.startswith("adm:resall:"))
async def cb_resall(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    _, _, pid, amt = cb.data.split(":")
    player = await _get(session, int(pid))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    from bot.game import inventory
    for r in balance.RESOURCES:
        inventory.add(player, r, int(amt))
    await _show_card(cb, session, player.id)
    await cb.answer(f"📦 +{amt} ко всем ресурсам")


@router.callback_query(F.data.startswith("adm:heal:"))
async def cb_heal(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    player = await _get(session, int(cb.data.rsplit(":", 1)[1]))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    player.hp = combat.max_hp()
    player.hp_at = _now()
    player.hunt_ready_at = None
    await _show_card(cb, session, player.id)
    await cb.answer("❤️ Полное здоровье")


@router.callback_query(F.data.startswith("adm:cool:"))
async def cb_cool(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    player = await _get(session, int(cb.data.rsplit(":", 1)[1]))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    past = _now()
    # бригады/крафт/стройка → готово
    exps = []
    for e in (player.expeditions or []):
        exps.append({**e, "ends_at": past.isoformat(), "notified": False})
    player.expeditions = exps
    if player.craft_ends_at:
        player.craft_ends_at = past
    if player.build_ends_at:
        player.build_ends_at = past
    # производство → готово
    if player.tavern and player.tavern.production:
        prod = {}
        for b, batch in player.tavern.production.items():
            prod[b] = {**batch, "ready_at": past.isoformat()}
        player.tavern.production = prod
    await _show_card(cb, session, player.id)
    await cb.answer("⏱ Кулдауны сняты — всё готово к забору")


@router.callback_query(F.data.startswith("adm:bonus:"))
async def cb_bonus(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    player = await _get(session, int(cb.data.rsplit(":", 1)[1]))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    player.bonus_next_at = None  # снять кулдаун выдачи
    player.bonus_kind = None
    buff.refresh(player)
    await _show_card(cb, session, player.id)
    await cb.answer(f"🎁 Выдан бонус: {buff.offer(player).name if buff.offer(player) else '—'}")


@router.callback_query(F.data.startswith("adm:gear:"))
async def cb_gear(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    player = await _get(session, int(cb.data.rsplit(":", 1)[1]))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    eq = {}
    for item in items.CATALOG.values():
        eq[item.slot] = items.make_entry(item.id, items.TIER_MAX)
    player.equipment = eq
    await _show_card(cb, session, player.id)
    await cb.answer("🎒 Выдана топ-снаряга (★★★)")


@router.callback_query(F.data.startswith("adm:build:"))
async def cb_build(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    player = await _get(session, int(cb.data.rsplit(":", 1)[1]))
    if player is None or player.tavern is None:
        await cb.answer("Нет таверны.", show_alert=True)
        return
    player.tavern.buildings = list(buildings.CATALOG)
    await _show_card(cb, session, player.id)
    await cb.answer("🏗 Все пристройки построены")


@router.callback_query(F.data.startswith("adm:god:"))
async def cb_god(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    player = await _get(session, int(cb.data.rsplit(":", 1)[1]))
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    from bot.game import inventory
    player.gold += 1_000_000
    for r in balance.RESOURCES:
        inventory.add(player, r, 9999)
    for k in ("malt", "flour", "ingot"):
        inventory.add(player, k, 9999)
    player.level = balance.MAX_LEVEL
    _sync_level(player)
    player.equipment = {it.slot: items.make_entry(it.id, items.TIER_MAX)
                        for it in items.CATALOG.values()}
    if player.tavern:
        player.tavern.buildings = list(buildings.CATALOG)
        player.tavern.reputation = max(player.tavern.reputation, 500)
    player.reputation = max(player.reputation, 500)
    player.hp = combat.max_hp()
    player.hp_at = _now()
    player.hunt_ready_at = None
    await _show_card(cb, session, player.id)
    await cb.answer("🦸 GOD-режим: всё по максимуму")


# ── Опасные действия с подтверждением ──────────────────────────────────────
@router.callback_query(F.data.startswith("adm:reset:"))
async def cb_reset(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    pid = int(cb.data.rsplit(":", 1)[1])
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, сбросить прогресс", callback_data=f"adm:resetok:{pid}")
    kb.button(text="↩️ Отмена", callback_data=f"adm:p:{pid}")
    kb.adjust(1)
    await _edit(cb, f"⚠️ Сбросить ВЕСЬ прогресс игрока <code>{pid}</code>?\n"
                    "Таверна снесётся, игрок начнёт с /start. Строка останется.",
                kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:resetok:"))
async def cb_resetok(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    pid = int(cb.data.rsplit(":", 1)[1])
    player = await _get(session, pid)
    if player is None:
        await cb.answer("Нет игрока.", show_alert=True)
        return
    await session.execute(delete(Tavern).where(Tavern.player_id == pid))
    # сброс полей игрока к стартовым
    player.level = 1
    player.gold = 100
    player.reputation = 0
    player.region = ""
    player.inventory = dict(balance.STARTING_INVENTORY)
    player.equipment = {}
    player.story = {}
    player.expeditions = []
    player.hp = None
    player.hp_at = None
    player.hunt_ready_at = None
    player.craft_item = None
    player.craft_ends_at = None
    player.build_item = None
    player.build_ends_at = None
    player.bonus_kind = None
    player.bonus_offered_at = None
    player.buff_kind = None
    player.buff_until = None
    player.bonus_next_at = None
    await session.flush()
    await _edit(cb, f"🔄 Прогресс игрока <code>{pid}</code> сброшен.",
                _back_kb(pid))
    await cb.answer("Сброшено")


@router.callback_query(F.data.startswith("adm:del:"))
async def cb_del(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    pid = int(cb.data.rsplit(":", 1)[1])
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить НАВСЕГДА", callback_data=f"adm:delok:{pid}")
    kb.button(text="↩️ Отмена", callback_data=f"adm:p:{pid}")
    kb.adjust(1)
    await _edit(cb, f"⚠️ Удалить игрока <code>{pid}</code> полностью (строку из БД)?",
                kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:delok:"))
async def cb_delok(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    pid = int(cb.data.rsplit(":", 1)[1])
    await session.execute(delete(Tavern).where(Tavern.player_id == pid))
    await session.execute(delete(Player).where(Player.id == pid))
    kb = InlineKeyboardBuilder()
    kb.button(text="👥 К списку", callback_data="adm:list:0")
    await _edit(cb, f"🗑 Игрок <code>{pid}</code> удалён подчистую.", kb)
    await cb.answer("Удалён")


def _back_kb(pid: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="↻ К карточке", callback_data=f"adm:p:{pid}")
    kb.button(text="👥 К списку", callback_data="adm:list:0")
    kb.adjust(1)
    return kb


# ── Мир и города ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:world")
async def cb_world(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    s = season.current()
    txt = "\n".join([
        "🌍 <b>МИР И СОБЫТИЯ</b>",
        "",
        f"Сезон: {s.emoji} {s.name} (спрос ×{s.demand_mult:g})",
        f"Ярмарка: {'идёт' if wld.is_fair() else 'нет'}",
        "",
        "<i>Запустить ярмарку вручную — кнопка ниже.</i>",
    ])
    kb = InlineKeyboardBuilder()
    kb.button(text="🎪 Открыть ярмарку", callback_data="adm:fair")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(1)
    await _edit(cb, txt, kb)
    await cb.answer()


@router.callback_query(F.data == "adm:fair")
async def cb_fair(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    from bot import announce
    from bot.db import repo
    world = await repo.get_or_create_world(session)
    wld.open_fair(world)
    await session.flush()
    chat_ids = await repo.all_chat_ids(session)
    await announce.broadcast_fair(cb.bot, "open", chat_ids, world)
    await cb.answer(f"🎪 Ярмарка открыта, анонс в {len(chat_ids)} чат(ов)",
                    show_alert=True)


@router.callback_query(F.data == "adm:cities")
async def cb_cities(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    chats = (await session.execute(select(KnownChat))).scalars().all()
    cities = {c.chat_id: c for c in
              (await session.execute(select(CityState))).scalars().all()}
    lines = ["🏙 <b>ГОРОДА / ЧАТЫ</b>", ""]
    for ch in chats:
        c = cities.get(ch.chat_id)
        mood = f"настр.{c.mood}" if c else "нет города"
        title = escape(ch.title or str(ch.chat_id))
        lines.append(f"• {title} <code>{ch.chat_id}</code> · {mood}")
    if not chats:
        lines.append("<i>Бот пока ни в одном чате.</i>")
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В меню", callback_data="adm:home")
    await _edit(cb, "\n".join(lines), kb)
    await cb.answer()


# ── Ввод точных значений (FSM) ─────────────────────────────────────────────
class AdmInput(StatesGroup):
    wait = State()


_PROMPTS = {
    "gold": "Введи новое количество золота (число):",
    "rep": "Введи новую репутацию (число):",
    "level": f"Введи уровень (1–{balance.MAX_LEVEL}):",
    "res": "Введи: <code>ресурс количество</code> (напр. <code>wood 500</code>).\n"
           f"Ресурсы: {', '.join(balance.RESOURCES)}, malt, flour, ingot",
    "find": "Введи Telegram ID или @username игрока:",
}


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_set(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(cb):
        return
    _, _, pid, field = cb.data.split(":")
    await state.set_state(AdmInput.wait)
    await state.update_data(pid=int(pid), field=field)
    await cb.message.answer(_PROMPTS.get(field, "Введи значение:"))
    await cb.answer()


@router.callback_query(F.data == "adm:find")
async def cb_find(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(cb):
        return
    await state.set_state(AdmInput.wait)
    await state.update_data(pid=0, field="find")
    await cb.message.answer(_PROMPTS["find"])
    await cb.answer()


@router.message(AdmInput.wait)
async def on_input(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    field = data.get("field")
    raw = (message.text or "").strip()
    await state.clear()

    if field == "find":
        player = None
        if raw.lstrip("-").isdigit():
            player = await session.get(Player, int(raw))
        else:
            uname = raw.lstrip("@")
            player = (await session.execute(
                select(Player).where(func.lower(Player.username) == uname.lower())
            )).scalar_one_or_none()
        if player is None:
            await message.answer("Не нашёл такого игрока.",
                                 reply_markup=_home_kb().as_markup())
            return
        await message.answer(_card_text(player),
                             reply_markup=_card_kb(player).as_markup())
        return

    pid = int(data.get("pid", 0))
    player = await session.get(Player, pid, with_for_update=True)
    if player is None:
        await message.answer("Игрок исчез.", reply_markup=_home_kb().as_markup())
        return

    try:
        if field == "res":
            name, _, amt = raw.partition(" ")
            player_inv_amt = int(amt.strip())
            from bot.game import inventory
            cur = inventory.get(player, name.strip())
            # задаём абсолютное значение
            inventory.add(player, name.strip(), player_inv_amt - cur)
            note = f"📦 {name.strip()} = {player_inv_amt}"
        else:
            val = int(raw)
            if field == "gold":
                player.gold = max(0, val); note = f"🪙 {player.gold}"
            elif field == "rep":
                player.reputation = max(0, val)
                if player.tavern:
                    player.tavern.reputation = max(0, val)
                note = f"⭐ {player.reputation}"
            elif field == "level":
                player.level = max(1, min(balance.MAX_LEVEL, val))
                _sync_level(player)
                note = f"📈 ур.{player.level}"
            else:
                note = "?"
    except (ValueError, AttributeError):
        await message.answer("Не разобрал. Нужно число (для ресурса: «имя число»).",
                             reply_markup=_card_kb(player).as_markup())
        return

    await message.answer(f"✅ {note}\n\n" + _card_text(player),
                         reply_markup=_card_kb(player).as_markup())
