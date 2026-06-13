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
    kb = InlineKeyboardBuilder()
    state, _ = logic.expedition_state(player)
    if state == "none":
        kb.button(text="⛏ Отправить работников", callback_data="exp_menu")
    elif state == "active":
        kb.button(text="⏳ Работники в пути", callback_data="exp_status")
    else:
        kb.button(text="🎒 Забрать добычу", callback_data="exp_claim")
    kb.button(text="💰 Собрать доход", callback_data="income")
    kb.button(text="📦 Склад", callback_data="warehouse")
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.button(text="🏗 Пристройки", callback_data="buildings")
    kb.button(text="🔨 Улучшить таверну", callback_data="upgrade")
    kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


def expedition_menu_kb(player: Player) -> InlineKeyboardMarkup:
    level = player.tavern.level if player.tavern else 1
    kb = InlineKeyboardBuilder()
    for res in balance.RESOURCES:
        amount = balance.expedition_yield(res, level, player.region)
        kb.button(
            text=f"{RESOURCE_EMOJI[res]} {RESOURCE_NAMES[res]} (+{amount})",
            callback_data=f"exp:{res}",
        )
    kb.button(text="↩️ Назад", callback_data="tavern")
    kb.adjust(2)
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
        elif bld.missing_requirements(tavern, b):
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
        and not bld.missing_requirements(tavern, building)
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
        if state == "ready":
            kb.button(text="🍺 Разлить в погреб", callback_data="prod_claim:brewery")
        elif state == "none":
            kb.button(text="★ Эль", callback_data="brew:1")
            kb.button(text="★★ Светлое", callback_data="brew:2")
            kb.button(text="★★★ Праздничное", callback_data="brew:3")
    kb.button(text="↩️ К пристройкам", callback_data="buildings")
    kb.adjust(1)
    return kb.as_markup()
