"""Все игровые тексты в одном месте."""

from bot.db.models import Player, Tavern
from bot.game import balance

WELCOME = (
    "🍺 <b>Добро пожаловать в Недоливск!</b>\n\n"
    "Городок, где эль льётся рекой (но всегда чуть-чуть не доливают).\n"
    "Здесь ты построишь свою таверну, прославишь её на весь край "
    "и обойдёшь конкурентов из общего чата.\n\n"
    "Начнём с главного — твоей таверны."
)

ASK_TAVERN_NAME = (
    "📜 Как назовём твою таверну?\n\n"
    "Напиши название сообщением (до 40 символов)."
)

NAME_TOO_LONG = "Слишком длинное название. До 40 символов, трактирщик!"

ASK_REGION = (
    "🗺 Где поставим таверну, <b>{name}</b>?\n\n"
    "🏔 <b>Северные холмы</b> — больше древесины\n"
    "🌊 <b>Речная долина</b> — больше зерна\n"
    "🌲 <b>Лесной край</b> — больше древесины\n"
    "🛤 <b>Торговый тракт</b> — больше хмеля"
)

CREATED = (
    "🎉 Таверна <b>{name}</b> открыта в регионе <b>{region}</b>!\n\n"
    "Стартовый капитал: 100 🪙\n"
    "Собирай ресурсы, улучшай таверну и зарабатывай репутацию."
)

GROUP_HINT = (
    "🍺 Игра «Недоливск» живёт в личных сообщениях.\n"
    "Напиши боту в личку, чтобы открыть свою таверну!"
)

ALREADY_REGISTERED = "У тебя уже есть таверна! Вот она:"


def tavern_screen(player: Player, tavern: Tavern) -> str:
    region = balance.REGIONS.get(player.region, player.region)
    return (
        f"🏠 <b>{tavern.name}</b>\n"
        f"📍 {region} · Уровень {tavern.level}\n\n"
        f"Тёплый свет очага, скрип половиц и запах свежего эля. "
        f"За стойкой — {player.first_name}, хозяин этого заведения.\n\n"
        f"👥 Вместимость: {tavern.capacity}\n"
        f"✨ Комфорт: {tavern.comfort}\n"
        f"💰 Доход: {tavern.income_rate} 🪙/час\n"
        f"⭐ Репутация: {tavern.reputation}\n\n"
        f"<b>Твои запасы:</b>\n"
        f"🪙 Золото: {player.gold}\n"
        f"🪵 Древесина: {player.wood} · 🌾 Зерно: {player.grain} · 🌿 Хмель: {player.hops}"
    )


def collect_success(gained: dict) -> str:
    return (
        "⛏ <b>Ресурсы собраны!</b>\n\n"
        f"🪵 Древесина: +{gained['wood']}\n"
        f"🌾 Зерно: +{gained['grain']}\n"
        f"🌿 Хмель: +{gained['hops']}\n\n"
        f"Следующий сбор через {balance.COLLECT_COOLDOWN_MIN} мин."
    )


def collect_cooldown(wait_minutes: int) -> str:
    return f"⏳ Работники ещё трудятся. Возвращайся через {wait_minutes} мин."


def income_success(gold: int) -> str:
    return f"💰 Посетители оставили <b>{gold} 🪙</b>. Неплохой день!"


def income_empty() -> str:
    return "💤 Касса пока пуста. Загляни чуть позже."


def upgrade_offer(tavern: Tavern, cost: dict) -> str:
    new_stats = balance.stats_for_level(tavern.level + 1)
    return (
        f"🔨 <b>Улучшение до уровня {tavern.level + 1}</b>\n\n"
        f"Стоимость:\n"
        f"🪙 {cost['gold']} · 🪵 {cost['wood']} · 🌾 {cost['grain']} · 🌿 {cost['hops']}\n\n"
        f"Что даст:\n"
        f"👥 Вместимость: {tavern.capacity} → {new_stats['capacity']}\n"
        f"✨ Комфорт: {tavern.comfort} → {new_stats['comfort']}\n"
        f"💰 Доход: {tavern.income_rate} → {new_stats['income_rate']} 🪙/час"
    )


def upgrade_success(new_level: int) -> str:
    return (
        f"🎉 <b>Таверна улучшена до уровня {new_level}!</b>\n"
        f"Слава о ней разносится по Недоливску. "
        f"+{balance.reputation_for_upgrade(new_level)} ⭐ репутации."
    )


def upgrade_not_enough(cost: dict, player: Player) -> str:
    return (
        "😕 Не хватает ресурсов на улучшение.\n\n"
        f"Нужно: 🪙 {cost['gold']} · 🪵 {cost['wood']} · "
        f"🌾 {cost['grain']} · 🌿 {cost['hops']}\n"
        f"У тебя: 🪙 {player.gold} · 🪵 {player.wood} · "
        f"🌾 {player.grain} · 🌿 {player.hops}"
    )


UPGRADE_MAX = "🏆 Таверна уже максимального уровня. Ты — легенда Недоливска!"
