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
    kb.button(text="🔨 Улучшить таверну", callback_data="upgrade")
    kb.adjust(1, 2, 1)
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
