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
    kb.button(text="🔨 Улучшить таверну", callback_data="upgrade")
    kb.adjust(1, 2, 2)
    return kb.as_markup()


def expedition_menu_kb(player: Player) -> InlineKeyboardMarkup:
    level = player.tavern.level if player.tavern else 1
    kb = InlineKeyboardBuilder()
    for res in ("wood", "grain", "hops"):
        amount = balance.expedition_yield(res, level, player.region)
        kb.button(
            text=f"{RESOURCE_EMOJI[res]} {RESOURCE_NAMES[res]} (+{amount})",
            callback_data=f"exp:{res}",
        )
    kb.button(text="↩️ Назад", callback_data="tavern")
    kb.adjust(1)
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
