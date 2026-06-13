"""Все игровые тексты в одном месте. Тон — жёсткий трактирный."""

from html import escape

from bot.db.models import Player, Tavern
from bot.game import balance, inventory, logic
from bot.game.balance import RESOURCE_EMOJI, RESOURCE_NAMES

WELCOME = (
    "🍺 <b>Недоливск, приятель.</b>\n\n"
    "Городишко, где эль не доливают, посуду не моют, "
    "а за лишний вопрос можно остаться без зубов.\n"
    "Хочешь свой кабак? Тогда хватит глазеть по сторонам — стройся."
)

ASK_TAVERN_NAME = (
    "📜 Как обзовёшь свою забегаловку?\n\n"
    "Пиши название (от 2 до 40 знаков). Думай головой — "
    "с этой вывеской тебе жить и спиваться."
)

NAME_TOO_LONG = "Ты бы ещё поэму накатал. От 2 до 40 знаков — и без соплей."

ASK_REGION = (
    "🗺 Где вкопаешь первый столб, <b>{name}</b>?\n\n"
    "❄️ <b>Северная глушь</b> — леса по самое горло (🪵 +50%), "
    "зато хмель дохнет на морозе (🌿 −25%)\n\n"
    "🌾 <b>Зелёные долины</b> — зерна хоть лопатой греби (🌾 +50%), "
    "но лес давно вырубили под пашню (🪵 −25%)\n\n"
    "🏜 <b>Красные пустоши</b> — дикий хмель крепче кулака (🌿 +50%), "
    "а зерно горит на солнце (🌾 −25%)\n\n"
    "Выбирай. Потом не скули."
)

CREATED = (
    "🍻 Ну всё, <b>{name}</b> открыта. Регион — <b>{region}</b>.\n\n"
    "В мошне 100 🪙 — не пропей в первый же вечер.\n"
    "Гони работников за ресурсами и поднимай этот сарай с колен."
)

GROUP_HINT = (
    "🍺 «Недоливск» наливает только в личке.\n"
    "Стучись к боту напрямую — здесь только языками чешут."
)

GROUP_NEED_TAVERN = (
    "🍺 А кабака-то у тебя ещё нет, мил человек.\n"
    "Завести можно только в личке — назвать да место выбрать. "
    "Жми кнопку, а как обзаведёшься — рули прямо отсюда: «гг таверна»."
)

GROUP_HELP = (
    "🍺 <b>Недоливск — командуй прямо в чате:</b>\n"
    "• <b>гг</b> или <b>гг таверна</b> — твой кабак\n"
    "• <b>гг перс</b> — персонаж и кузница\n"
    "• <b>гг склад</b> — запасы\n"
    "• <b>гг кузница</b> — заказать снаряжение\n"
    "• <b>гг карта</b> — карта мира\n"
    "• <b>гг топ</b> — доска почёта\n"
    "Кнопки чужой панели жать нельзя — только хозяин."
)

ALREADY_REGISTERED = "У тебя уже есть кабак, забыл? Вот он:"


def craft_line(player) -> str:
    """Строка о состоянии заказа в кузнице для экрана персонажа."""
    from bot.game import items as it
    from bot.game import logic

    state, minutes = logic.craft_state(player)
    if state == "active":
        item_id, tier = it.parse_entry(player.craft_item)
        item = it.CATALOG.get(item_id)
        name = f"{item.name} {it.TIER_STARS[tier]}" if item else "вещь"
        return f"⚒ Мастер куёт «{name}» — ещё {minutes // 60} ч {minutes % 60} мин."
    if state == "ready":
        return "🎁 Мастер закончил заказ — забери вещь!"
    return ""


def _fmt_minutes(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"


def _build_line(player: Player) -> str:
    """Строка о текущей стройке для экрана таверны."""
    from bot.game import buildings as bld

    state, minutes = bld.build_state(player)
    if state == "active":
        b = bld.CATALOG.get(player.build_item)
        name = b.name if b else "пристройка"
        return f"🏗 Строится {name} — ещё {_fmt_minutes(minutes)}.\n"
    if state == "ready":
        b = bld.CATALOG.get(player.build_item)
        return f"🏗 {b.name if b else 'Пристройка'} достроена — загляни в Пристройки!\n"
    return ""


def _cost_line(cost: dict, player: Player) -> str:
    """🪙/🪵/… N ✅/❌ — по содержимому словаря стоимости."""
    emoji = {"gold": "🪙", **RESOURCE_EMOJI}
    parts = []
    for key, need in cost.items():
        if not need:
            continue
        have = player.gold if key == "gold" else inventory.get(player, key)
        mark = "✅" if have >= need else "❌"
        parts.append(f"{emoji.get(key, key)} {need} {mark}")
    return " · ".join(parts)


def buildings_screen(player: Player, tavern: Tavern) -> str:
    from bot.game import buildings as bld

    lines = [
        "🏗 <b>Пристройки</b>",
        "Каждая открывает своё производство. Деньги и сырьё — вперёд.\n",
    ]
    for bid in bld.ORDER:
        b = bld.CATALOG[bid]
        if bld.is_built(tavern, bid):
            status = "✓ построено"
        elif player.build_item == bid:
            _, m = bld.build_state(player)
            status = f"🏗 строится, ещё {_fmt_minutes(m)}"
        elif bld.missing_requirements(tavern, b):
            req = ", ".join(r.name for r in bld.missing_requirements(tavern, b))
            status = f"🔒 нужна: {req}"
        else:
            status = "доступна к стройке"
        lines.append(f"{b.emoji} <b>{b.name}</b> — {status}")
    return "\n".join(lines)


def building_detail(building, player: Player, tavern: Tavern) -> str:
    from bot.game import buildings as bld

    head = f"{building.emoji} <b>{building.name}</b>\n<i>{building.description}</i>\n"
    gives = f"Откроет: {building.unlocks}\n" if building.unlocks else ""

    if bld.is_built(tavern, building.id):
        return head + gives + "\n✓ Уже построено. Работает."

    miss = bld.missing_requirements(tavern, building)
    if miss:
        req = ", ".join(r.name for r in miss)
        return head + gives + f"\n🔒 Сначала построй: {req}."

    state, m = bld.build_state(player)
    if state != "none":
        return head + gives + (
            "\n🏗 Сейчас уже идёт другая стройка — одна за раз. "
            f"Освободятся работники через {_fmt_minutes(m)}."
        )

    return (
        head + gives +
        f"\nСтройка: {building.build_hours} ч\n"
        f"Цена: {_cost_line(building.cost, player)}"
    )


def build_started(building, hours: int) -> str:
    return (
        f"🏗 Заложили фундамент под <b>{building.name}</b>. "
        f"Артель обещает управиться за {hours} ч — и не факт, что не соврёт."
    )


def build_not_enough(building, player: Player) -> str:
    return (
        f"😕 На <b>{building.name}</b> не хватает.\n"
        f"Надо: {_cost_line(building.cost, player)}\n"
        "Гони работников за сырьём и возвращайся."
    )


def build_ready_notification(building) -> str:
    return (
        f"🏗 <b>{building.name}</b> достроена! {building.description}\n"
        "Загляни в Пристройки — пора пускать в дело."
    )


# ===== Производство =====

def production_screen(building, player: Player, tavern: Tavern) -> str:
    from bot.game import production as prod

    head = f"{building.emoji} <b>{building.name}</b>\n<i>{building.description}</i>\n"
    if building.id == "mill":
        malt = inventory.get(player, "malt")
        level = tavern.level
        cin = prod.mill_inputs(level)
        out = prod.mill_output(level)
        state, minutes = prod.state(tavern, "mill")
        if state == "active":
            status = f"⏳ Мелется — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🌱 Солод готов — забирай!"
        else:
            status = "😴 Жернова простаивают."
        m_emoji = balance.GOODS_EMOJI["malt"]
        m_name = balance.GOODS_NAMES["malt"]
        g_emoji = RESOURCE_EMOJI["grain"]
        return (
            head +
            f"\n{m_emoji} {m_name} на складе: {malt}\n"
            f"{status}\n\n"
            f"Помол (ур. {level}): {g_emoji} {cin['grain']} → {m_emoji} {out} "
            f"{m_name.lower()}, {prod.MILL_MINUTES} мин\n"
            f"В закромах: {g_emoji} {inventory.get(player, 'grain')}"
        )
    if building.id == "brewery":
        level = tavern.level
        prods = tavern.products or {}
        stock = " · ".join(
            f"{prod.ALE_STARS[t]} {prods.get(str(t), 0)}" for t in (1, 2, 3)
        )
        state, minutes = prod.state(tavern, "brewery")
        if state == "active":
            t = int(tavern.production["brewery"]["tier"])
            status = f"⏳ Бродит {prod.ALE_STARS[t]} — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            t = int(tavern.production["brewery"]["tier"])
            status = f"🍺 {prod.ALE_STARS[t]} готов — разливай в погреб!"
        else:
            status = "😴 Чаны пусты. Выбери, что варить."
        inv = lambda r: inventory.get(player, r)  # noqa: E731
        return (
            head +
            f"\n🛢 Погреб: {stock}\n{status}\n\n"
            f"Рецепты (ур. {level}, выход {12 * level} кружек):\n"
            f"★ {8*level}🌱 {5*level}🌿 {6*level}💧 — 4 ч\n"
            f"★★ то же + {6*level}🍯 — 8 ч\n"
            f"★★★ то же + {12*level}🍯 — 12 ч\n"
            f"Есть: 🌱{inv('malt')} 🌿{inv('hops')} 💧{inv('water')} 🍯{inv('honey')}"
        )
    return head + "\nПроизводство этого здания — скоро."


def brew_not_enough(tier: int, cin: dict) -> str:
    from bot.game import production as prod

    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    need = " ".join(f"{ico.get(r, r)}{q}" for r, q in cin.items())
    return f"😕 На {prod.ALE_STARS[tier]} не хватает: {need}. Доготовь сырьё."


def brew_ready_notification(tier: int) -> str:
    from bot.game import production as prod

    return (
        f"🍺 <b>Эль {prod.ALE_STARS[tier]} доварился!</b> "
        "Разлей в погреб — кружки сами себя не нальют."
    )


def mill_started(amount: int, minutes: int) -> str:
    return (
        f"🌾 Жернова закрутились. Будет ~{amount} 🌱 солода через "
        f"{_fmt_minutes(minutes)}. Мельник уже тянется к кружке."
    )


def mill_not_enough(cin: dict) -> str:
    return (
        f"😕 Зерна мало: на помол нужно 🌾 {cin['grain']}. "
        "Гони работников в поля."
    )


def malt_ready_notification() -> str:
    return (
        "🌱 <b>Солод смолот!</b> Забирай с мельницы — "
        "и в пивоварню, пока мыши не добрались."
    )


def tavern_screen(player: Player, tavern: Tavern) -> str:
    region = balance.REGIONS.get(player.region, player.region)
    state, minutes = logic.expedition_state(player)
    if state == "active":
        res = player.expedition_resource
        exp_line = (
            f"\n⏳ Работники горбатятся за {RESOURCE_EMOJI[res]} "
            f"{RESOURCE_NAMES[res].lower()} — приползут через {_fmt_minutes(minutes)}.\n"
        )
    elif state == "ready":
        exp_line = "\n🎒 Работники приволокли добычу — забирай, пока не пропили!\n"
    else:
        exp_line = "\n😴 Работники дрыхнут на сене. Пни их — пусть пользу приносят.\n"

    build_line = _build_line(player)

    return (
        f"🏠 <b>{escape(tavern.name)}</b>\n"
        f"📍 {region} · Уровень {tavern.level}\n\n"
        f"Скрипят половицы, воняет элем и мокрой псиной. "
        f"За стойкой — {escape(player.first_name)}, "
        f"и спорить с хозяином тут не принято.\n"
        f"{exp_line}{build_line}\n"
        f"👥 Вместимость: {tavern.capacity}\n"
        f"✨ Комфорт: {tavern.comfort}\n"
        f"💰 Доход: {tavern.income_rate} 🪙/час\n"
        f"⭐ Репутация: {tavern.reputation}\n\n"
        f"🪙 Золото: {player.gold}"
    )


def warehouse_screen(player: Player, tavern: Tavern) -> str:
    lines = [
        f"📦 <b>Склад «{escape(tavern.name)}»</b>",
        "Темно, пыльно, по углам шуршат крысы. Вот что ещё не растащили:\n",
        f"🪙 Золото: {player.gold}\n",
        "<b>Запасы:</b>",
    ]
    for res in balance.RESOURCES:
        lines.append(
            f"{RESOURCE_EMOJI[res]} {RESOURCE_NAMES[res]}: {inventory.get(player, res)}"
        )
    if tavern.level < balance.MAX_LEVEL:
        cost = balance.upgrade_cost(tavern.level)
        emoji = {"gold": "🪙", **RESOURCE_EMOJI}
        lines.append(f"\n<b>До перестройки (ур. {tavern.level + 1}):</b>")
        for key in ("gold", "wood", "grain", "hops"):
            have = player.gold if key == "gold" else inventory.get(player, key)
            mark = "✅" if have >= cost[key] else "❌"
            lines.append(f"{emoji[key]} {have} / {cost[key]} {mark}")
    else:
        lines.append("\n🏆 Выше строить некуда — разве что до небес.")
    return "\n".join(lines)


def storehouse_caption(player: Player, tavern: Tavern) -> str:
    """Короткая подпись к складской ведомости (ресурсы — на самой картинке)."""
    lines = [
        f"📦 <b>Складская ведомость «{escape(tavern.name)}»</b>",
        f"🪙 Золото: {player.gold}",
    ]
    if tavern.level < balance.MAX_LEVEL:
        cost = balance.upgrade_cost(tavern.level)
        emoji = {"gold": "🪙", **RESOURCE_EMOJI}
        parts = []
        for key in ("gold", "wood", "grain", "hops"):
            have = player.gold if key == "gold" else inventory.get(player, key)
            mark = "✅" if have >= cost[key] else "❌"
            parts.append(f"{emoji[key]} {have}/{cost[key]}{mark}")
        lines.append(f"\n<b>До перестройки (ур. {tavern.level + 1}):</b>")
        lines.append(" · ".join(parts))
    else:
        lines.append("\n🏆 Выше строить некуда — разве что до небес.")
    return "\n".join(lines)


def expedition_menu(player: Player) -> str:
    level = player.tavern.level if player.tavern else 1
    pay = balance.worker_pay(level)
    return (
        "⛏ <b>Куда гнать работников?</b>\n\n"
        f"Ходка — {balance.EXPEDITION_HOURS} ч. Плата — {pay} 🪙 вперёд, "
        "и попробуй не заплати.\n"
        "Один ресурс за раз: жадность в Недоливске не лечится."
    )


def expedition_started(resource: str, pay: int) -> str:
    return (
        f"🚶 Работники потащились за {RESOURCE_EMOJI[resource]} "
        f"{RESOURCE_NAMES[resource].lower()} (−{pay} 🪙).\n"
        f"Вернутся через {balance.EXPEDITION_HOURS} ч — если волки не сожрут."
    )


def expedition_no_gold(pay: int, gold: int) -> str:
    return (
        f"Платить нечем, голодранец: надо {pay} 🪙, у тебя {gold} 🪙. "
        "Бесплатно тут даже не чихают."
    )


def expedition_in_progress(minutes: int) -> str:
    return (
        f"⏳ Ещё пашут. Вернутся через {_fmt_minutes(minutes)} — "
        "раньше не жди и не ной."
    )


def expedition_claimed(resource: str, amount: int, lucky: bool = False) -> str:
    if lucky:
        return (
            f"🍀 <b>Счастливая вылазка!</b>\n\n"
            f"Работники наткнулись на нетронутую делянку — "
            f"добыча двойная!\n"
            f"{RESOURCE_EMOJI[resource]} {RESOURCE_NAMES[resource]}: +{amount}\n\n"
            "Сегодня даже крысы на складе аплодируют."
        )
    return (
        f"🎒 <b>Добыча на складе!</b>\n\n"
        f"{RESOURCE_EMOJI[resource]} {RESOURCE_NAMES[resource]}: +{amount}\n\n"
        "Работники утёрли пот и ждут новых приказов."
    )


RESOURCE_INSTRUMENTAL = {
    "wood": "древесиной",
    "grain": "зерном",
    "hops": "хмелем",
    "water": "водой",
    "honey": "мёдом",
    "berries": "ягодами",
    "game": "дичью",
    "ore": "рудой",
    "clay": "глиной",
    "herbs": "травами",
}


def expedition_returned(resource: str) -> str:
    return (
        f"🔔 Работники приволокли {RESOURCE_EMOJI[resource]} "
        f"{RESOURCE_INSTRUMENTAL[resource]}!\n"
        "Забирай быстрее, пока крысы не растащили, а пьянь не спёрла."
    )


def income_success(gold: int) -> str:
    return (
        f"💰 Пьянь оставила в кассе <b>{gold} 🪙</b>. "
        "Половина монет липкие, но золото есть золото."
    )


def income_empty() -> str:
    return "💤 Касса пуста, как башка завсегдатая. Заглядывай позже."


def upgrade_offer(tavern: Tavern, cost: dict) -> str:
    new_stats = balance.stats_for_level(tavern.level + 1)
    return (
        f"🔨 <b>Перестройка до уровня {tavern.level + 1}</b>\n\n"
        f"Выложишь:\n"
        f"🪙 {cost['gold']} · 🪵 {cost['wood']} · 🌾 {cost['grain']} · 🌿 {cost['hops']}\n\n"
        f"Получишь:\n"
        f"👥 Вместимость: {tavern.capacity} → {new_stats['capacity']}\n"
        f"✨ Комфорт: {tavern.comfort} → {new_stats['comfort']}\n"
        f"💰 Доход: {tavern.income_rate} → {new_stats['income_rate']} 🪙/час\n\n"
        "Плотники деньги вперёд берут и сдачу не дают."
    )


def upgrade_success(new_level: int) -> str:
    return (
        f"🔨 <b>Готово! Уровень {new_level}.</b>\n"
        f"Соседи завидуют, конкуренты скрипят зубами. "
        f"+{balance.reputation_for_upgrade(new_level)} ⭐ к репутации."
    )


def upgrade_not_enough(cost: dict, player: Player) -> str:
    return (
        "😕 С такими запасами только сортир во дворе пристроить.\n\n"
        f"Надо: 🪙 {cost['gold']} · 🪵 {cost['wood']} · "
        f"🌾 {cost['grain']} · 🌿 {cost['hops']}\n"
        f"У тебя: 🪙 {player.gold} · 🪵 {inventory.get(player, 'wood')} · "
        f"🌾 {inventory.get(player, 'grain')} · 🌿 {inventory.get(player, 'hops')}\n\n"
        "Иди работай."
    )


UPGRADE_MAX = (
    "🏆 Выше некуда — твой кабак и так легенда Недоливска. "
    "Теперь главное — не профукать."
)


MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
ZONE_EMOJI = {"north_wilds": "❄️", "green_valleys": "🌾", "red_wastes": "🏜"}


def rating_screen(rows: list, total_gdp: int, total_taverns: int) -> str:
    """rows: [(место, название, имя владельца, уровень, регион, ВВП, репутация)]"""
    lines = [
        "🏆 <b>ДОСКА ПОЧЁТА НЕДОЛИВСКА</b>",
        f"Кабаков в городе: {total_taverns} · "
        f"ВВП города: <b>{total_gdp:,}</b> 🪙".replace(",", " "),
        "",
    ]
    for place, name, owner, level, region, gdp, rep in rows:
        medal = MEDALS.get(place, f"{place}.")
        zone = ZONE_EMOJI.get(region, "")
        gdp_s = f"{gdp:,}".replace(",", " ")
        lines.append(
            f"{medal} <b>{escape(name)}</b> {zone} ур.{level}\n"
            f"      ВВП {gdp_s} 🪙 · ⭐ {rep} · хозяин: {escape(owner)}"
        )
    lines.append("")
    lines.append(
        "Не нашёл себя в списке? Так и запишем: "
        "пьёшь больше, чем зарабатываешь."
    )
    return "\n".join(lines)


# ===== Персонаж и кузница =====

def _item_bonus_line(item) -> str:
    parts = []
    if item.income_pct: parts.append(f"+{item.income_pct}% доход")
    if item.yield_pct: parts.append(f"+{item.yield_pct}% добыча")
    if item.yield_wood_pct: parts.append(f"+{item.yield_wood_pct}% 🪵")
    if item.speed_pct: parts.append(f"−{item.speed_pct}% время вылазки")
    if item.pay_discount_pct: parts.append(f"−{item.pay_discount_pct}% плата")
    if item.damage: parts.append(f"⚔{item.damage}")
    if item.crit: parts.append(f"💥{item.crit}%")
    if item.armor: parts.append(f"🛡{item.armor}")
    if item.luck: parts.append(f"🍀{item.luck}")
    return " · ".join(parts) if parts else "—"


def character_screen(player, craft_line: str = "") -> str:
    from bot.game import items as it

    equipment = getattr(player, "equipment", None) or {}
    stats = it.combat_stats(equipment)
    worn = len(equipment)
    body = (
        f"🧍 <b>{escape(player.first_name)}, хозяин кабака</b>\n"
        f"Морда кирпичом, руки в мозолях. Надето: {worn}/{len(it.SLOTS)}.\n"
    )
    if craft_line:
        body += craft_line + "\n"
    body += (
        f"\n⚔ Урон: {stats['damage']} · 💥 Крит: {stats['crit']}% · "
        f"🛡 Броня: {stats['armor']} · 🍀 Удача: {stats['luck']}\n"
        f"🍀 Счастливая вылазка (добыча ×2): "
        f"{balance.lucky_chance(stats['luck'])}%\n"
    )
    bonuses = []
    if it.income_multiplier(equipment) > 1:
        bonuses.append(f"+{round((it.income_multiplier(equipment)-1)*100)}% доход")
    ym = it.yield_multiplier(equipment, "grain")
    if ym > 1:
        bonuses.append(f"+{round((ym-1)*100)}% добыча")
    if it.speed_multiplier(equipment) < 1:
        bonuses.append(f"−{round((1-it.speed_multiplier(equipment))*100)}% время вылазок")
    if it.pay_multiplier(equipment) < 1:
        bonuses.append(f"−{round((1-it.pay_multiplier(equipment))*100)}% плата работникам")
    if bonuses:
        body += "💼 Хозяйство: " + " · ".join(bonuses) + "\n"
    body += "\nГолый трактирщик — смешной трактирщик. Загляни в кузницу."
    return body


def forge_screen(player) -> str:
    return (
        "⚒ <b>Кузница Недоливска</b>\n"
        "Мастер плюёт на ладони и смотрит на твоё золото.\n"
        "Один заказ за раз. Деньги вперёд, претензии — никогда.\n\n"
        f"🪙 {player.gold} · 🪵 {inventory.get(player, 'wood')} · "
        f"🌾 {inventory.get(player, 'grain')} · 🌿 {inventory.get(player, 'hops')}"
    )


def _tier_bonus_line(item, tier: int) -> str:
    parts = []
    if item.income_pct: parts.append(f"+{item.income_pct * tier}% доход")
    if item.yield_pct: parts.append(f"+{item.yield_pct * tier}% добыча")
    if item.yield_wood_pct: parts.append(f"+{item.yield_wood_pct * tier}% 🪵")
    if item.speed_pct: parts.append(f"−{item.speed_pct * tier}% время вылазки")
    if item.pay_discount_pct: parts.append(f"−{item.pay_discount_pct * tier}% плата")
    if item.damage: parts.append(f"⚔{item.damage * tier}")
    if item.crit: parts.append(f"💥{item.crit * tier}%")
    if item.armor: parts.append(f"🛡{item.armor * tier}")
    if item.luck: parts.append(f"🍀{item.luck * tier}")
    return " · ".join(parts) if parts else "—"


def forge_item_screen(item, player, cur_tier: int, next_tier: int) -> str:
    from bot.game import items as it

    if cur_tier >= it.TIER_MAX:
        return (
            f"<b>{item.name} {it.TIER_STARS[it.TIER_MAX]}</b> · "
            f"слот: {it.SLOTS[item.slot]}\n"
            f"<i>{item.description}</i>\n\n"
            f"Даёт: {_tier_bonus_line(item, it.TIER_MAX)}\n\n"
            "Мастерская работа. Лучше уже не выкуют — даже не проси."
        )
    c = it.tier_cost(item, next_tier)
    hours = it.tier_hours(item, next_tier)
    have_mark = lambda k, have: "✅" if have >= c.get(k, 0) else "❌"
    head = f"<b>{item.name} {it.TIER_STARS[next_tier]}</b> · слот: {it.SLOTS[item.slot]}"
    if cur_tier > 0:
        head += (
            f"\nПерековка: {it.TIER_STARS[cur_tier]} → {it.TIER_STARS[next_tier]} "
            f"({it.TIER_NAMES[next_tier]})"
        )
    return (
        f"{head}\n"
        f"<i>{item.description}</i>\n\n"
        f"Будет давать: {_tier_bonus_line(item, next_tier)}\n"
        f"Ковать: {hours} ч\n\n"
        f"Цена: 🪙 {c.get('gold',0)} {have_mark('gold', player.gold)} · "
        f"🪵 {c.get('wood',0)} {have_mark('wood', inventory.get(player, 'wood'))} · "
        f"🌾 {c.get('grain',0)} {have_mark('grain', inventory.get(player, 'grain'))} · "
        f"🌿 {c.get('hops',0)} {have_mark('hops', inventory.get(player, 'hops'))}"
    )


def craft_started(item, tier: int, hours: int) -> str:
    from bot.game import items as it

    return (
        f"⚒ Мастер забрал плату и взялся за <b>{item.name} "
        f"{it.TIER_STARS[tier]}</b>.\n"
        f"Будет готово через {hours} ч. Не стой над душой."
    )


def craft_not_enough(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"На «{item.name} {it.TIER_STARS[tier]}» у тебя кишка тонка "
        "и мошна пуста. Иди заработай, потом приходи."
    )


def craft_in_progress(minutes: int) -> str:
    return f"⚒ Мастер ещё куёт. Готово через {_fmt_minutes(minutes)}. Не зуди."


def craft_ready_notification(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"🔔 Мастер закончил <b>{item.name} {it.TIER_STARS[tier]}</b>!\n"
        "Забирай, пока не перепродал кому побогаче."
    )


def craft_claimed(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"⚒ <b>{item.name} {it.TIER_STARS[tier]}</b> — твоё!\n"
        f"Надето. {_tier_bonus_line(item, tier)}.\n"
        "Носи и не потеряй по пьяни."
    )
