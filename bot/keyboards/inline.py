from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Player
from bot.game import balance, logic
from bot.game.balance import REGIONS, RESOURCE_EMOJI, RESOURCE_NAMES

REGION_EMOJI = {"north_wilds": "❄️", "green_valleys": "🌾", "red_wastes": "🏜"}


def create_tavern_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 Создать таверну", callback_data="create_tavern")
    return kb.as_markup()


def pm_link_kb(username: str) -> InlineKeyboardMarkup:
    """Кнопка-ссылка в личку бота (для регистрации из общего чата)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🍺 Завести кабак в личке", url=f"https://t.me/{username}?start=play")
    return kb.as_markup()


def regions_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, title in REGIONS.items():
        kb.button(text=f"{REGION_EMOJI[code]} {title}", callback_data=f"region:{code}")
    kb.adjust(2)
    return kb.as_markup()


def tavern_kb(player: Player) -> InlineKeyboardMarkup:
    from bot.game import story_state

    kb = InlineKeyboardBuilder()
    sizes: list[int] = []

    if story_state.get_pending(player):  # незакрытое событие — даём вернуться к нему
        kb.button(text="🔔 Тебя ждёт гость!", callback_data="event_open")
        sizes.append(1)

    c = logic.expedition_counts(player, player.tavern)
    if c.ready:
        exp_label = f"🎒 Бригады вернулись ({c.ready})"
    elif c.out:
        exp_label = f"⏳ Бригады в пути ({c.out}/{c.total})"
    else:
        exp_label = "⛏ Отправить бригады"
    kb.button(text=exp_label, callback_data="exp_menu")
    kb.button(text="💰 Собрать доход", callback_data="income")
    kb.button(text="📦 Склад", callback_data="warehouse")
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.button(text="🏗 Пристройки", callback_data="buildings")
    kb.button(text="🔨 Улучшить таверну", callback_data="upgrade")
    kb.button(text="❓ Как играть", callback_data="help")
    kb.adjust(*sizes, 1, 2, 2, 1, 1)
    return kb.as_markup()


def expedition_menu_kb(player: Player) -> InlineKeyboardMarkup:
    tavern = player.tavern
    level = tavern.level if tavern else 1
    c = logic.expedition_counts(player, tavern)
    kb = InlineKeyboardBuilder()
    sizes: list[int] = []
    if c.ready:
        kb.button(text=f"🎒 Забрать вернувшихся ({c.ready})", callback_data="exp_claim")
        sizes.append(1)
    if c.free > 0:
        for res in balance.RESOURCES:
            amount = balance.expedition_yield(res, level, player.region)
            kb.button(
                text=f"{RESOURCE_EMOJI[res]} {RESOURCE_NAMES[res]} (+{amount})",
                callback_data=f"exp:{res}",
            )
        sizes += [2] * (len(balance.RESOURCES) // 2)
    kb.button(text="↩️ Назад", callback_data="tavern")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()


def upgrade_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Улучшить", callback_data="upgrade_confirm")
    kb.button(text="↩️ Назад", callback_data="tavern")
    kb.adjust(2)
    return kb.as_markup()


def claim_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎒 Забрать добычу", callback_data="exp_claim")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ К таверне", callback_data="tavern")
    return kb.as_markup()


def character_kb(craft_ready: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if craft_ready:
        kb.button(text="🎁 Забрать у мастера", callback_data="craft_claim")
    kb.button(text="⚒ Кузница", callback_data="forge")
    kb.button(text="🏠 К таверне", callback_data="tavern_new")
    kb.adjust(1)
    return kb.as_markup()


def forge_kb(player: Player | None = None) -> InlineKeyboardMarkup:
    from bot.game.items import CATALOG, TIER_STARS, equipped_tier

    equipment = getattr(player, "equipment", None) if player else None
    kb = InlineKeyboardBuilder()
    for item in CATALOG.values():
        tier = equipped_tier(equipment, item.id)
        label = f"{item.name} {TIER_STARS[tier]}" if tier else item.name
        kb.button(text=label, callback_data=f"forge_item:{item.id}")
    kb.button(text="↩️ Назад", callback_data="character")
    kb.adjust(2)
    return kb.as_markup()


def forge_item_kb(item_id: str, maxed: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not maxed:
        kb.button(text="⚒ Заказать", callback_data=f"forge_make:{item_id}")
    kb.button(text="↩️ В кузницу", callback_data="forge")
    kb.adjust(2)
    return kb.as_markup()


def craft_claim_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Забрать вещь", callback_data="craft_claim")
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.adjust(1)
    return kb.as_markup()


def buildings_kb(player, tavern) -> InlineKeyboardMarkup:
    from bot.game import buildings as bld

    kb = InlineKeyboardBuilder()
    for bid in bld.ORDER:
        b = bld.CATALOG[bid]
        if bld.is_built(tavern, bid):
            mark = "✓"
        elif player.build_item == bid:
            mark = "🏗"
        elif bld.missing_requirements(tavern, b) or bld.rep_locked(tavern, b):
            mark = "🔒"
        else:
            mark = ""
        label = f"{b.emoji} {b.name} {mark}".strip()
        kb.button(text=label, callback_data=f"build_open:{bid}")
    kb.button(text="↩️ К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def building_detail_kb(player, tavern, building) -> InlineKeyboardMarkup:
    from bot.game import buildings as bld

    kb = InlineKeyboardBuilder()
    can_build = (
        not bld.is_built(tavern, building.id)
        and bld.build_state(player)[0] == "none"
        and bld.buildable(tavern, building)
    )
    if can_build:
        kb.button(text="🏗 Построить", callback_data=f"build_make:{building.id}")
    kb.button(text="↩️ Назад", callback_data="buildings")
    kb.adjust(1)
    return kb.as_markup()


def buildings_back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 К пристройкам", callback_data="buildings")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def buildings_notify_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 Пристройки", callback_data="buildings")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def production_kb(player, tavern, building) -> InlineKeyboardMarkup:
    from bot.game import production as prod

    kb = InlineKeyboardBuilder()
    state, _ = prod.state(tavern, building.id)
    if building.id == "mill":
        if state == "ready":
            kb.button(text="🌱 Забрать солод", callback_data="prod_claim:mill")
        elif state == "none":
            kb.button(text="🌾 Молоть солод", callback_data="prod_make:mill")
    elif building.id == "brewery":
        phase, _ = prod.brew_phase(tavern)
        if phase == "ready":
            kb.button(text="🍺 Разлить в погреб", callback_data="prod_claim:brewery")
            if int(tavern.production["brewery"]["tier"]) < 3:
                kb.button(text="🛢 Выдержать (рискнуть)", callback_data="brew_age")
        elif phase in ("ripe", "overripe"):
            kb.button(text="🍺 Разлить выдержку", callback_data="prod_claim:brewery")
        elif phase == "empty":
            kb.button(text="★ Эль", callback_data="brew:1")
            kb.button(text="★★ Светлое", callback_data="brew:2")
            kb.button(text="★★★ Праздничное", callback_data="brew:3")
    elif building.id == "meadery":
        if state == "ready":
            kb.button(text="🍶 Разлить в погреб", callback_data="prod_claim:meadery")
        elif state == "none":
            kb.button(text="🍶 Медовуха", callback_data="meadery:mead")
            kb.button(text="🌿 Сбитень", callback_data="meadery:sbiten")
    elif building.id == "kitchen":
        if state == "ready":
            kb.button(text="🍖 Забрать в кладовую", callback_data="prod_claim:kitchen")
        elif state == "none":
            kb.button(text="🍖 Жаркое", callback_data="kitchen:roast")
    elif building.id == "winery":
        if state == "ready":
            kb.button(text="🍷 Разлить в погреб", callback_data="prod_claim:winery")
        elif state == "none":
            kb.button(text="🍷 Вино", callback_data="winery:wine")
    kb.button(text="↩️ К пристройкам", callback_data="buildings")
    kb.adjust(1)
    return kb.as_markup()
