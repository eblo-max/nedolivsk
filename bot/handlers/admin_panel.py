"""Фундаментальная админ-панель через бота (только для ADMIN_ID).

/admin — сводка мира, список игроков с пагинацией, карточка игрока со всеми
данными и полным управлением: золото/репутация/уровень/ресурсы/снаряга/здания/
кулдауны/бонус/god-режим/сброс/удаление. Точные значения — через ввод (FSM).
"""

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import settings
from bot.db import repo
from bot.db.models import CityState, KnownChat, MarketOrder, Player, Tavern
from bot.game import (
    balance, buff, buildings, combat, inventory, items, market, production, raid,
    season,
)
from bot.game import world as wld
from bot.keyboards.inline import raid_gather_kb
from bot.sender import deliver

# Ресурсы, которые можно раздавать (сырьё + полуфабрикаты) — анти-опечатка.
_GIVABLE = set(balance.RESOURCES) | {"malt", "flour", "ingot"}

router = Router()

PAGE = 8


def _is_admin(uid: int) -> bool:
    return settings.admin_id != 0 and uid == settings.admin_id


async def _guard_cb(cb: CallbackQuery) -> bool:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Не для тебя.", show_alert=True)
        return False
    return True


def _alog(cb: CallbackQuery, session: AsyncSession, text: str) -> None:
    """Записать действие админа в журнал."""
    repo.add_log(session, "admin", cb.from_user.id, text)


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
    kb.button(text="📊 Аналитика", callback_data="adm:stats")
    kb.button(text="🎁 Раздать всем", callback_data="adm:grantall")
    kb.button(text="📣 Рассылка", callback_data="adm:cast")
    kb.button(text="⚔️ Рейд-босс", callback_data="adm:raid")
    kb.button(text="📜 Логи", callback_data="adm:logs:all:0")
    kb.button(text="🌍 Мир и события", callback_data="adm:world")
    kb.button(text="🏙 Города/чаты", callback_data="adm:cities")
    kb.button(text="🔄 Обновить", callback_data="adm:home")
    kb.adjust(2, 2, 2, 2, 2)
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
        f"❤️ HP: {hp}/{combat.max_hp(player)} · охота: {_ago(player.hunt_ready_at) if player.hunt_ready_at else 'готов'}",
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
    kb.button(text="🍺 Выдать товар", callback_data=f"adm:set:{i}:goods")
    kb.button(text="❤️ Полный HP", callback_data=f"adm:heal:{i}")
    kb.button(text="⏱ Снять кулдауны", callback_data=f"adm:cool:{i}")
    kb.button(text="🎁 Выдать бонус", callback_data=f"adm:bonus:{i}")
    kb.button(text="🎒 Топ-снаряга", callback_data=f"adm:gear:{i}")
    kb.button(text="🏗 Достроить всё", callback_data=f"adm:build:{i}")
    kb.button(text="🦸 GOD-режим", callback_data=f"adm:god:{i}")
    kb.button(text="🔄 Сброс прогресса", callback_data=f"adm:reset:{i}")
    kb.button(text="🗑 Удалить", callback_data=f"adm:del:{i}")
    kb.button(text="📜 История игрока", callback_data=f"adm:plog:{i}:0")
    kb.button(text="↻ Обновить", callback_data=f"adm:p:{i}")
    kb.button(text="👥 К списку", callback_data="adm:list:0")
    kb.adjust(4, 2, 2, 3, 2, 2, 2, 2, 1, 2)
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
    _alog(cb, session, f"🪙 {int(delta):+} → id{player.id} (={player.gold})")
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
    _alog(cb, session, f"⭐ {int(delta):+} → id{player.id} (={player.reputation})")
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
    _alog(cb, session, f"📈 уровень → id{player.id} (={player.level})")
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
    _alog(cb, session, f"📦 +{amt} ко всем ресурсам → id{player.id}")
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
    player.hp = combat.max_hp(player)
    player.hp_at = _now()
    player.hunt_ready_at = None
    _alog(cb, session, f"❤️ полный HP → id{player.id}")
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
    _alog(cb, session, f"⏱ снял кулдауны → id{player.id}")
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
    _alog(cb, session, f"🎁 выдал бонус → id{player.id}")
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
    _alog(cb, session, f"🎒 выдал топ-снарягу → id{player.id}")
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
    _alog(cb, session, f"🏗 достроил все здания → id{player.id}")
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
    player.hp = combat.max_hp(player)
    player.hp_at = _now()
    player.hunt_ready_at = None
    _alog(cb, session, f"🦸 GOD-режим → id{player.id}")
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
    await repo.delete_player_orders(session, pid)  # биржевые лоты не осиротят
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
    _alog(cb, session, f"🔄 сбросил прогресс → id{pid}")
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
    await repo.delete_player_orders(session, pid)
    await session.execute(delete(Player).where(Player.id == pid))
    _alog(cb, session, f"🗑 удалил игрока id{pid}")
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
    from bot.game import worldevent
    s = season.current()
    ev = worldevent.active()
    txt = "\n".join([
        "🌍 <b>МИР И СОБЫТИЯ</b>",
        "",
        f"Сезон: {s.emoji} {s.name} (спрос ×{s.demand_mult:g})",
        f"Ярмарка: {'идёт' if wld.is_fair() else 'нет'}",
        f"Погода: {ev.emoji + ' ' + ev.name if ev else 'ясно'}",
        "",
        "<i>Запустить ярмарку или погодное событие — кнопками ниже.</i>",
    ])
    kb = InlineKeyboardBuilder()
    kb.button(text="🎪 Открыть ярмарку", callback_data="adm:fair")
    kb.button(text="🌦 Погода / события", callback_data="adm:weather")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(1)
    await _edit(cb, txt, kb)
    await cb.answer()


@router.callback_query(F.data == "adm:weather")
async def cb_weather(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    from bot.game import worldevent
    ev = worldevent.active()
    lines = ["🌦 <b>ПОГОДА / СОБЫТИЯ</b>", "",
             f"Сейчас: {ev.emoji + ' ' + ev.name if ev else 'ясно (события нет)'}",
             "", "<i>Жми событие — запустится сразу на весь мир с анонсом.</i>"]
    kb = InlineKeyboardBuilder()
    if ev is not None:
        kb.button(text="🌤 Снять событие", callback_data="adm:weatheroff")
    for eid, e in worldevent.EVENTS.items():
        kb.button(text=f"{e.emoji} {e.name}", callback_data=f"adm:weather:{eid}")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(*([1] if ev else []), 2, 2, 2, 2, 1, 1)
    await _edit(cb, "\n".join(lines), kb)
    await cb.answer()


@router.callback_query(F.data == "adm:weatheroff")
async def cb_weather_off(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    from datetime import timedelta

    from bot.db import repo
    from bot.game import worldevent
    world = await repo.get_or_create_world(session)
    world.event_kind = None
    world.event_until = None
    world.event_next_at = _now() + timedelta(hours=balance.WORLDEVENT_COOLDOWN_MIN_HOURS)
    worldevent.set_active(None)
    _alog(cb, session, "🌤 снял мировое событие")
    await cb.answer("Событие снято.")
    await cb_weather(cb, session)


@router.callback_query(F.data.startswith("adm:weather:"))
async def cb_weather_set(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    from datetime import timedelta

    from bot import announce
    from bot.db import repo
    from bot.game import worldevent
    eid = cb.data.split(":", 2)[2]
    e = worldevent.EVENTS.get(eid)
    if e is None:
        await cb.answer("Нет такого события.", show_alert=True)
        return
    now = _now()
    world = await repo.get_or_create_world(session)
    world.event_kind = eid
    world.event_until = now + timedelta(hours=e.hours)
    world.event_next_at = None
    # Мода — выбираем случайный товар (как в авто-цикле); иначе сбрасываем.
    if e.good_price != 1.0:
        import random as _r
        from bot.game import production as _prod
        world.event_good = _r.choice(list(_prod.GOODS))
    else:
        world.event_good = None
    await session.flush()
    worldevent.set_active(eid, world.event_until, world.event_good)
    await announce.world_event(cb.bot, session,
                               texts.worldevent_announce(e, world.event_good), now)
    _alog(cb, session, f"🌦 запустил событие {eid} ({e.hours}ч)")
    await cb.answer(f"{e.emoji} {e.name} запущено — анонс разослан!", show_alert=True)
    await cb_weather(cb, session)


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
    _alog(cb, session, "🎪 открыл ярмарку вручную")
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


# ── Журнал событий ─────────────────────────────────────────────────────────
LOGPAGE = 12


def _log_line(e) -> str:
    ts = e.ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    when = ts.strftime("%d.%m %H:%M")
    tag = "🛠" if e.kind == "admin" else "👤"
    return f"<code>{when}</code> {tag} <code>{e.actor_id}</code> {escape(e.text)}"


def _logs_kb(kind: str, page: int, total: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=("• Все" if kind == "all" else "Все"), callback_data="adm:logs:all:0")
    kb.button(text=("• 🛠 Админ" if kind == "admin" else "🛠 Админ"),
              callback_data="adm:logs:admin:0")
    kb.button(text=("• 👤 Игроки" if kind == "player" else "👤 Игроки"),
              callback_data="adm:logs:player:0")
    nav = []
    if page > 0:
        kb.button(text="◀️", callback_data=f"adm:logs:{kind}:{page - 1}")
        nav.append(1)
    if (page + 1) * LOGPAGE < total:
        kb.button(text="▶️", callback_data=f"adm:logs:{kind}:{page + 1}")
        nav.append(1)
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(3, *(nav or [1]), 1)
    return kb


@router.callback_query(F.data.startswith("adm:logs:"))
async def cb_logs(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    _, _, kind, page_s = cb.data.split(":")
    page = int(page_s)
    flt = None if kind == "all" else kind
    total = await repo.count_logs(session, kind=flt)
    rows = await repo.recent_logs(session, kind=flt, limit=LOGPAGE,
                                  offset=page * LOGPAGE)
    pages = max(1, (total + LOGPAGE - 1) // LOGPAGE)
    title = {"all": "ВСЕ", "admin": "АДМИН", "player": "ИГРОКИ"}.get(kind, kind)
    lines = [f"📜 <b>ЖУРНАЛ · {title}</b> ({total}) · стр. {page + 1}/{pages}", ""]
    lines += [_log_line(e) for e in rows] or ["<i>пусто</i>"]
    await _edit(cb, "\n".join(lines), _logs_kb(kind, page, total))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:plog:"))
async def cb_plog(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    _, _, pid_s, page_s = cb.data.split(":")
    pid, page = int(pid_s), int(page_s)
    total = await repo.count_logs(session, actor_id=pid)
    rows = await repo.recent_logs(session, actor_id=pid, limit=LOGPAGE,
                                  offset=page * LOGPAGE)
    pages = max(1, (total + LOGPAGE - 1) // LOGPAGE)
    lines = [f"📜 <b>ИСТОРИЯ id{pid}</b> ({total}) · стр. {page + 1}/{pages}", ""]
    lines += [_log_line(e) for e in rows] or ["<i>событий нет</i>"]
    kb = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        kb.button(text="◀️", callback_data=f"adm:plog:{pid}:{page - 1}")
        nav.append(1)
    if (page + 1) * LOGPAGE < total:
        kb.button(text="▶️", callback_data=f"adm:plog:{pid}:{page + 1}")
        nav.append(1)
    kb.button(text="↻ К карточке", callback_data=f"adm:p:{pid}")
    kb.adjust(*(nav or [1]), 1)
    await _edit(cb, "\n".join(lines), kb)
    await cb.answer()


# ── Аналитика (экономика / активность / по чатам) ──────────────────────────
async def _stats_text(session: AsyncSession) -> str:
    now = _now()
    players = await session.scalar(select(func.count(Player.id))) or 0
    gold_sum = await session.scalar(select(func.coalesce(func.sum(Player.gold), 0))) or 0
    avg = (gold_sum // players) if players else 0

    rich = (await session.execute(
        select(Player).order_by(Player.gold.desc()).limit(3))).scalars().all()

    async def _seen(days):
        return await session.scalar(select(func.count(Player.id)).where(
            Player.last_seen_at.is_not(None),
            Player.last_seen_at >= now - timedelta(days=days))) or 0
    d1, d7, d30 = await _seen(1), await _seen(7), await _seen(30)
    new1 = await session.scalar(select(func.count(Player.id)).where(
        Player.created_at >= now - timedelta(days=1))) or 0

    world = await repo.get_or_create_world(session)
    gluts = sorted(
        ((g, v) for g, v in (world.market or {}).items() if g != "_t"),
        key=lambda kv: -abs(kv[1]))[:6]
    mkt_lines = []
    for g, glut in gluts:
        f = market.factor(world, g)
        nm = production.GOODS[g].name if g in production.GOODS else g
        arrow = "📉" if glut > 0 else "📈"
        mkt_lines.append(f"  {arrow} {nm}: {round((f - 1) * 100):+d}% (перекос {int(glut)})")

    border = await session.scalar(
        select(func.count(MarketOrder.id)).where(MarketOrder.qty > 0)) or 0
    bvol = await session.scalar(select(func.coalesce(
        func.sum(MarketOrder.qty * MarketOrder.unit_price), 0))
        .where(MarketOrder.qty > 0)) or 0

    titles = {c.chat_id: c.title for c in
              (await session.execute(select(KnownChat))).scalars().all()}
    chat_rows = (await session.execute(
        select(Player.chat_id, func.count(Player.id),
               func.coalesce(func.sum(Player.gold), 0))
        .group_by(Player.chat_id)
        .order_by(func.coalesce(func.sum(Player.gold), 0).desc()).limit(8))).all()
    chat_lines = []
    for cid, n, g in chat_rows:
        nm = "личка" if cid is None else (titles.get(cid) or str(cid))
        chat_lines.append(
            f"  {escape(str(nm))[:22]}: {n} игр., {int(g):,}🪙".replace(",", " "))

    parts = ["📊 <b>АНАЛИТИКА НЕДОЛИВСКА</b>", ""]
    parts += [
        "💰 <b>Экономика</b>",
        f"  Золота в мире: {gold_sum:,}".replace(",", " ") + f" (в среднем {avg:,}/игрок)".replace(",", " "),
        "  Богачи: " + (", ".join(f"{escape(p.first_name or str(p.id))} {p.gold:,}".replace(",", " ") for p in rich[:3]) or "—"),
        f"  Биржа: {border} лотов, оборот ~{int(bvol):,}🪙".replace(",", " "),
    ]
    parts += ["", "🏪 <b>Рынок (перекосы цен)</b>"] + (mkt_lines or ["  ровно, без перекосов"])
    parts += ["", "🟢 <b>Активность</b>",
              f"  За сутки: {d1} · за 7д: {d7} · за 30д: {d30}",
              f"  Новичков за сутки: {new1}"]
    parts += ["", "💬 <b>По чатам (золото)</b>"] + (chat_lines or ["  нет данных"])
    return "\n".join(parts)


@router.callback_query(F.data == "adm:stats")
async def cb_stats(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="adm:stats")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(2)
    await _edit(cb, await _stats_text(session), kb)
    await cb.answer()


# ── Раздать всем / Рассылка ─────────────────────────────────────────────────
@router.callback_query(F.data == "adm:grantall")
async def cb_grantall(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    n = await session.scalar(select(func.count(Player.id))) or 0
    kb = InlineKeyboardBuilder()
    kb.button(text="🪙 Золото всем", callback_data="adm:giveall:gold")
    kb.button(text="📦 Ресурс всем", callback_data="adm:giveall:res")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(2, 1)
    await _edit(cb, (
        "🎁 <b>РАЗДАТЬ ВСЕМ</b>\n\n"
        f"Игроков в мире: <b>{n}</b>.\n"
        "Золото — добавится к текущему у каждого; ресурс — на склад каждому. "
        "Можно и отнять (минус)."
    ), kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:giveall:"))
async def cb_giveall(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(cb):
        return
    field = "grant_gold_all" if cb.data.split(":")[2] == "gold" else "grant_res_all"
    await state.set_state(AdmInput.wait)
    await state.update_data(pid=0, field=field)
    await cb.message.answer(_PROMPTS[field])
    await cb.answer()


@router.callback_query(F.data == "adm:cast")
async def cb_cast(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    chats = await session.scalar(select(func.count(KnownChat.chat_id))) or 0
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💬 Во все чаты ({chats})", callback_data="adm:cast:chats")
    kb.button(text="✉️ В личку игрокам", callback_data="adm:cast:dm")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(1)
    await _edit(cb, (
        "📣 <b>РАССЫЛКА</b>\n\n"
        "💬 <b>Во все чаты</b> — пост уйдёт во все общие чаты, где есть бот. "
        "Это доходит до всех, кто играет в группе. <i>Рекомендуется.</i>\n\n"
        "✉️ <b>В личку</b> — только тем, кто открывал бота в личных сообщениях. "
        "Тех, кто играет лишь в группе, Telegram писать в ЛС не даёт — до них "
        "не дойдёт."
    ), kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:cast:"))
async def cb_cast_mode(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _guard_cb(cb):
        return
    field = "cast_chats" if cb.data.split(":")[2] == "chats" else "cast_dm"
    await state.set_state(AdmInput.wait)
    await state.update_data(pid=0, field=field)
    await cb.message.answer(_PROMPTS[field])
    await cb.answer()


# ── Рейд-босс ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "adm:raid")
async def cb_raid_menu(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    active = await repo.get_active_raid(session)
    kb = InlineKeyboardBuilder()
    if active is not None:
        spec = raid.BOSSES.get(active.boss_key)
        nm = f"{spec.emoji if spec else ''} {spec.name if spec else active.boss_key}"
        phase = ("идёт СБОР" if active.status == "gathering"
                 else f"БИТВА — {max(0, active.hp)}/{active.max_hp} HP")
        kb.button(text="💀 Убрать активного", callback_data="adm:raidkill")
        head = (f"⚔️ <b>РЕЙД-БОСС</b>\n\nСейчас: {nm} ({phase}), "
                f"бойцов {raid.registered_count(active)}. Новый можно призвать "
                "после его смерти/ухода.")
    else:
        for key, b in raid.BOSSES.items():
            kb.button(text=f"{b.emoji} {b.name} (HP~сила^{raid.HP_POWER_EXP}, пол {b.min_hp})",
                      callback_data=f"adm:raidspawn:{key}")
        head = ("⚔️ <b>РЕЙД-БОСС</b>\n\nПризвать босса — сперва 20-мин сбор во всех "
                "чатах, затем битва. HP растёт от СИЛЫ записавшихся. Бьют записавшиеся, награда — "
                "золото поровну на всех, кто бил, плюс шанс на эксклюзивный трофей.")
    kb.button(text="🏠 В меню", callback_data="adm:home")
    kb.adjust(1)
    await _edit(cb, head, kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:raidspawn:"))
async def cb_raid_spawn(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    if await repo.get_active_raid(session) is not None:
        await cb.answer("Уже есть активный босс.", show_alert=True)
        return
    key = cb.data.split(":", 2)[2]
    spec = raid.BOSSES.get(key)
    if spec is None:
        await cb.answer("Нет такого босса.", show_alert=True)
        return
    boss = repo.create_raid(session, key, raid.gather_until())
    await session.flush()  # нужен boss.id для кнопок
    _alog(cb, session, f"⚔️ призван рейд-босс {key} (сбор {raid.GATHER_MINUTES} мин)")
    from bot.handlers.raid import send_raid_announce
    text = texts.raid_gather_screen(boss)
    chat_ids = await repo.all_chat_ids(session)
    msgs: dict[str, int] = {}
    for cid in chat_ids:  # видео грузится 1 раз, дальше по чатам — по кэш-file_id
        sent = await deliver(lambda c=cid: send_raid_announce(
            cb.bot, c, boss, text, raid_gather_kb(boss.id)), what=f"raid→{cid}")
        if sent is not None:
            msgs[str(cid)] = sent.message_id
    boss.messages = msgs  # запоминаем сообщения — нотифаер правит отсчёт/HP
    raid.set_active(boss.id)  # меню таверны сразу покажет кнопку «Рейд-босс»
    # Личечным игрокам — пуш-анонс (живой экран откроют кнопкой «Рейд-босс» в меню).
    from datetime import timedelta
    cut = _now() - timedelta(days=7)
    pids = [r[0] for r in (await session.execute(
        select(Player.id).where(Player.last_seen_at >= cut))).all()]
    for uid in pids:
        repo.queue_notify(session, uid, texts.raid_push_dm(boss), kind="raid")
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В меню", callback_data="adm:home")
    await _edit(cb, f"⚔️ {spec.emoji} {spec.name} призван — сбор {raid.GATHER_MINUTES} "
                    f"мин. В чаты: {len(msgs)}/{len(chat_ids)}. Пуш в личку: {len(pids)}.", kb)
    await cb.answer("Босс призван! Идёт сбор.")


@router.callback_query(F.data == "adm:raidkill")
async def cb_raid_kill(cb: CallbackQuery, session: AsyncSession) -> None:
    if not await _guard_cb(cb):
        return
    boss = await repo.get_active_raid(session, lock=True)
    if boss is not None:
        boss.status = "expired"
        _alog(cb, session, f"⚔️ снят рейд-босс {boss.boss_key}")
    raid.set_active(None)  # убрать кнопку «Рейд-босс» из меню
    await cb.answer("Босс снят.")
    await cb_raid_menu(cb, session)


# ── Ввод точных значений (FSM) ─────────────────────────────────────────────
class AdmInput(StatesGroup):
    wait = State()


_PROMPTS = {
    "gold": "Введи новое количество золота (число):",
    "rep": "Введи новую репутацию (число):",
    "level": f"Введи уровень (1–{balance.MAX_LEVEL}):",
    "res": "Введи: <code>ресурс количество</code> (напр. <code>wood 500</code>).\n"
           f"Ресурсы: {', '.join(balance.RESOURCES)}, malt, flour, ingot",
    "goods": "Введи: <code>товар количество</code> (напр. <code>ale2 5</code>) — "
             "добавится в погреб.\nТовары: " + ", ".join(production.GOODS),
    "find": "Введи Telegram ID или @username игрока:",
    "grant_gold_all": "Сколько золота раздать КАЖДОМУ игроку? (число; минус — отнять)",
    "grant_res_all": "Что раздать ВСЕМ: <code>ресурс количество</code> "
                     "(напр. <code>wood 200</code>).\nРесурсы: "
                     + ", ".join(balance.RESOURCES) + ", malt, flour, ingot",
    "cast_dm": "Пришли текст рассылки — уйдёт В ЛИЧКУ тем, кто открывал бота "
               "в ЛС. Можно с HTML-разметкой, либо ФОТО с подписью:",
    "cast_chats": "Пришли текст рассылки — уйдёт ВО ВСЕ ЧАТЫ с ботом. "
                  "Можно с HTML-разметкой, либо ФОТО с подписью:",
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
    # У фото текст лежит в caption, а не в text. Берём оба + сам file_id картинки —
    # чтобы рассылку можно было слать постом с картинкой.
    raw = (message.text or message.caption or "").strip()
    photo_id = message.photo[-1].file_id if message.photo else None
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

    # ── Массовые операции (на всех игроков) ──
    if field == "cast_chats":
        if not raw and not photo_id:
            await message.answer("Пусто — отменено (пришли текст или фото).",
                                 reply_markup=_home_kb().as_markup())
            return
        cap = raw[:1024]  # подпись к фото ограничена Telegram (1024)
        chat_ids = await repo.all_chat_ids(session)
        sent = 0
        for cid in chat_ids:
            if photo_id:
                f = lambda c=cid: message.bot.send_photo(c, photo_id, caption=cap or None)
            else:
                f = lambda c=cid: message.bot.send_message(c, raw)
            if await deliver(f, what=f"cast→{cid}") is not None:
                sent += 1
        repo.add_log(session, "admin", message.from_user.id,
                     f"📣 рассылка в чаты{'(фото)' if photo_id else ''}: "
                     f"{sent}/{len(chat_ids)}")
        await message.answer(f"📣 Отправлено в {sent} из {len(chat_ids)} чатов.",
                             reply_markup=_home_kb().as_markup())
        return

    if field == "cast_dm":
        if not raw and not photo_id:
            await message.answer("Пусто — отменено (пришли текст или фото).",
                                 reply_markup=_home_kb().as_markup())
            return
        ids = [r[0] for r in (await session.execute(select(Player.id))).all()]
        for uid in ids:
            repo.queue_notify(session, uid, raw[:1024], photo=photo_id)
        repo.add_log(session, "admin", message.from_user.id,
                     f"📣 рассылка в личку{'(фото)' if photo_id else ''}: "
                     f"{len(ids)} игрокам")
        await message.answer(
            f"📣 В очередь поставлено {len(ids)} сообщений — разойдутся в "
            "ближайшие минуты (по мере отправки).",
            reply_markup=_home_kb().as_markup())
        return

    if field == "grant_gold_all":
        if not raw.lstrip("-").isdigit():
            await message.answer("Нужно число.", reply_markup=_home_kb().as_markup())
            return
        amt = int(raw)
        await session.execute(
            update(Player).values(gold=func.greatest(0, Player.gold + amt)))
        n = await session.scalar(select(func.count(Player.id))) or 0
        repo.add_log(session, "admin", message.from_user.id,
                     f"🪙 раздал {amt:+} золота всем ({n})")
        await message.answer(f"🪙 Раздал {amt:+} золота всем игрокам ({n}).",
                             reply_markup=_home_kb().as_markup())
        return

    if field == "grant_res_all":
        name, _, amt_s = raw.partition(" ")
        res = name.strip().lower()
        if res not in _GIVABLE or not amt_s.strip().lstrip("-").isdigit():
            await message.answer(
                "Формат: <code>ресурс количество</code>, ресурс из списка.",
                reply_markup=_home_kb().as_markup())
            return
        amt = int(amt_s.strip())
        players = (await session.execute(select(Player))).scalars().all()
        for p in players:
            inventory.add(p, res, amt)
        repo.add_log(session, "admin", message.from_user.id,
                     f"📦 раздал {res} {amt:+} всем ({len(players)})")
        await message.answer(f"📦 Раздал {res} {amt:+} всем игрокам ({len(players)}).",
                             reply_markup=_home_kb().as_markup())
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
            cur = inventory.get(player, name.strip())
            # задаём абсолютное значение
            inventory.add(player, name.strip(), player_inv_amt - cur)
            note = f"📦 {name.strip()} = {player_inv_amt}"
        elif field == "goods":
            name, _, amt = raw.partition(" ")
            name = name.strip()
            if name not in production.GOODS or player.tavern is None:
                raise ValueError
            prods = dict(player.tavern.products or {})
            prods[name] = max(0, prods.get(name, 0) + int(amt.strip()))  # добавляем
            player.tavern.products = prods
            note = f"🍺 {production.GOODS[name].name} = {prods[name]}"
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

    repo.add_log(session, "admin", message.from_user.id,
                 f"✏️ задал {field} → id{player.id}: {note}")
    await message.answer(f"✅ {note}\n\n" + _card_text(player),
                         reply_markup=_card_kb(player).as_markup())
