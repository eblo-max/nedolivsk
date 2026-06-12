"""Все игровые тексты в одном месте."""

from html import escape

from bot.db.models import Player, Tavern
from bot.game import balance, logic
from bot.game.balance import RESOURCE_EMOJI, RESOURCE_NAMES

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

NAME_TOO_LONG = "Название должно быть от 2 до 40 символов, трактирщик!"

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
    "Отправляй работников за ресурсами, улучшай таверну и зарабатывай репутацию."
)

GROUP_HINT = (
    "🍺 Игра «Недоливск» живёт в личных сообщениях.\n"
    "Напиши боту в личку, чтобы открыть свою таверну!"
)

ALREADY_REGISTERED = "У тебя уже есть таверна! Вот она:"


def _fmt_minutes(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"


def tavern_screen(player: Player, tavern: Tavern) -> str:
    region = balance.REGIONS.get(player.region, player.region)
    state, minutes = logic.expedition_state(player)
    if state == "active":
        res = player.expedition_resource
        exp_line = (
            f"\n⏳ Работники добывают {RESOURCE_EMOJI[res]} "
            f"{RESOURCE_NAMES[res].lower()} — вернутся через {_fmt_minutes(minutes)}.\n"
        )
    elif state == "ready":
        exp_line = "\n🎒 Работники вернулись с добычей — забери её!\n"
    else:
        exp_line = "\n😴 Работники отдыхают и ждут приказа.\n"

    return (
        f"🏠 <b>{escape(tavern.name)}</b>\n"
        f"📍 {region} · Уровень {tavern.level}\n\n"
        f"Тёплый свет очага, скрип половиц и запах свежего эля. "
        f"За стойкой — {escape(player.first_name)}, хозяин этого заведения.\n"
        f"{exp_line}\n"
        f"👥 Вместимость: {tavern.capacity}\n"
        f"✨ Комфорт: {tavern.comfort}\n"
        f"💰 Доход: {tavern.income_rate} 🪙/час\n"
        f"⭐ Репутация: {tavern.reputation}\n\n"
        f"🪙 Золото: {player.gold}"
    )


def warehouse_screen(player: Player, tavern: Tavern) -> str:
    lines = [
        f"📦 <b>Склад таверны «{escape(tavern.name)}»</b>\n",
        f"🪙 Золото: {player.gold}\n",
        "<b>Ресурсы:</b>",
        f"🪵 Древесина: {player.wood}",
        f"🌾 Зерно: {player.grain}",
        f"🌿 Хмель: {player.hops}",
    ]
    if tavern.level < balance.MAX_LEVEL:
        cost = balance.upgrade_cost(tavern.level)
        have = {
            "gold": player.gold,
            "wood": player.wood,
            "grain": player.grain,
            "hops": player.hops,
        }
        emoji = {"gold": "🪙", **RESOURCE_EMOJI}
        lines.append(f"\n<b>До улучшения (ур. {tavern.level + 1}):</b>")
        for key in ("gold", "wood", "grain", "hops"):
            mark = "✅" if have[key] >= cost[key] else "❌"
            lines.append(f"{emoji[key]} {have[key]} / {cost[key]} {mark}")
    else:
        lines.append("\n🏆 Таверна максимального уровня.")
    return "\n".join(lines)


def expedition_menu(player: Player) -> str:
    level = player.tavern.level if player.tavern else 1
    pay = balance.worker_pay(level)
    return (
        "⛏ <b>Куда отправить работников?</b>\n\n"
        f"Вылазка длится {balance.EXPEDITION_HOURS} ч, "
        f"работникам нужно заплатить {pay} 🪙.\n"
        "Добывать можно только один ресурс за раз — выбирай с умом."
    )


def expedition_started(resource: str, pay: int) -> str:
    return (
        f"🚶 Работники отправились за {RESOURCE_EMOJI[resource]} "
        f"{RESOURCE_NAMES[resource].lower()} (−{pay} 🪙).\n"
        f"Вернутся через {balance.EXPEDITION_HOURS} ч."
    )


def expedition_no_gold(pay: int, gold: int) -> str:
    return f"Нечем платить работникам: нужно {pay} 🪙, у тебя {gold} 🪙."


def expedition_in_progress(minutes: int) -> str:
    return f"⏳ Работники ещё в пути. Вернутся через {_fmt_minutes(minutes)}."


def expedition_claimed(resource: str, amount: int) -> str:
    return (
        f"🎒 <b>Добыча получена!</b>\n\n"
        f"{RESOURCE_EMOJI[resource]} {RESOURCE_NAMES[resource]}: +{amount}\n\n"
        "Работники готовы к новой вылазке."
    )


RESOURCE_INSTRUMENTAL = {
    "wood": "древесиной",
    "grain": "зерном",
    "hops": "хмелем",
}


def expedition_returned(resource: str) -> str:
    return (
        f"🔔 Работники вернулись с {RESOURCE_EMOJI[resource]} "
        f"{RESOURCE_INSTRUMENTAL[resource]}!\n"
        "Забери добычу, пока её не растащили крысы."
    )


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
