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


def welcome_kb() -> InlineKeyboardMarkup:
    """Хаб на приветственном экране: завести кабак + разделы инфо."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 Завести кабак", callback_data="create_tavern")
    kb.button(text="📖 Как играть", callback_data="how_play")
    kb.button(text="🏰 Живой город", callback_data="living_city")
    kb.button(text="👥 Затащить в чат", callback_data="add_chat")
    kb.button(text="⌨️ Команды", callback_data="commands")
    kb.adjust(1, 2, 2)
    return kb.as_markup()


def info_nav_kb() -> InlineKeyboardMarkup:
    """Навигация между разделами инфо-хаба."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Как играть", callback_data="how_play")
    kb.button(text="🏰 Живой город", callback_data="living_city")
    kb.button(text="👥 Затащить в чат", callback_data="add_chat")
    kb.button(text="⌨️ Команды", callback_data="commands")
    kb.adjust(2, 2)
    return kb.as_markup()


def add_chat_kb(username: str) -> InlineKeyboardMarkup:
    """Раздел «в чат»: кнопка-ссылка добавления + навигация."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="➕ Добавить в беседу",
        url=f"https://t.me/{username}?startgroup=play",
    )
    kb.button(text="📖 Как играть", callback_data="how_play")
    kb.button(text="🏰 Живой город", callback_data="living_city")
    kb.button(text="⌨️ Команды", callback_data="commands")
    kb.adjust(1, 2, 1)
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

    if story_state.get_retail(player):  # гости ждут решения по сбыту
        kb.button(text="🍺 Гости ждут заказ!", callback_data="retail_open")
        sizes.append(1)
    if story_state.get_trade(player):  # купец ждёт ответа по цене
        kb.button(text="🤝 Купец торгуется!", callback_data="trade_open")
        sizes.append(1)
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
    auc = player.tavern.auction or None
    if auc and auc.get("top_bid"):
        auc_label = f"🔨 Торги: {auc['top_bid']}🪙!"
    elif auc:
        auc_label = "🔨 Торги идут"
    else:
        auc_label = "🔨 Аукцион"

    kb.button(text=exp_label, callback_data="exp_menu")
    kb.button(text="💰 Собрать доход", callback_data="income")
    kb.button(text="🏪 Рынок", callback_data="market")
    kb.button(text=auc_label, callback_data="auction")
    kb.button(text="📦 Склад", callback_data="warehouse")
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.button(text="🏗 Пристройки", callback_data="buildings")
    kb.button(text="🔨 Улучшить таверну", callback_data="upgrade")
    kb.button(text="ℹ️ О игре", callback_data="info")
    kb.adjust(*sizes, 1, 2, 2, 2, 1)
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
        from bot.game import season
        for res in balance.RESOURCES:
            amount = int(balance.expedition_yield(res, level, player.region)
                         * season.yield_mult(res))
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


def trade_kb(offer: dict) -> InlineKeyboardMarkup:
    p = offer["prices"]
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🪙 Дёшево · {p[0]}/шт", callback_data="trd:0")
    kb.button(text=f"💰 По рынку · {p[1]}/шт", callback_data="trd:1")
    kb.button(text=f"🤑 Дорого · {p[2]}/шт", callback_data="trd:2")
    kb.button(text="🚪 Не продавать", callback_data="trd:no")
    kb.adjust(1)
    return kb.as_markup()


def trade_counter_kb(counter: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🤝 Идёт · {counter}/шт", callback_data="trd:ok")
    kb.button(text="💬 Дожать ещё", callback_data="trd:push")
    kb.button(text="🚪 Послать", callback_data="trd:no")
    kb.adjust(1)
    return kb.as_markup()


def loot_kb(drop_id: int) -> InlineKeyboardMarkup:
    """Кнопка подкидыша — кто первый нажал, тот подобрал (публичная)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🤲 Поднять!", callback_data=f"loot:{drop_id}")
    return kb.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ К таверне", callback_data="tavern")
    return kb.as_markup()


def retail_kb(total: int) -> InlineKeyboardMarkup:
    """Подтверждение сбыта гостям: налить (продать) или придержать товар."""
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🍺 Налить гостям · +{total} 🪙", callback_data="retail_sell")
    kb.button(text="🤚 Придержать товар", callback_data="retail_hold")
    kb.adjust(1)
    return kb.as_markup()


def character_kb(craft_ready: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if craft_ready:
        kb.button(text="🎁 Забрать у мастера", callback_data="craft_claim")
    kb.button(text="⚒ Кузница", callback_data="forge")
    kb.button(text="🏹 Охота", callback_data="hunt")
    kb.button(text="👥 Горожане", callback_data="citizens")
    kb.button(text="🏠 К таверне", callback_data="tavern_new")
    kb.adjust(1)
    return kb.as_markup()


def hunt_menu_kb(player) -> InlineKeyboardMarkup:
    from bot.game import combat
    kb = InlineKeyboardBuilder()
    sizes = []
    if combat.can_heal(player):
        kb.button(text="🍖 Подлечиться", callback_data="healmenu")
        sizes.append(1)
    for e in combat.ENEMIES:
        kb.button(text=f"{e.emoji} {e.name}", callback_data=f"hbeast:{e.id}")
    n = len(combat.ENEMIES)
    sizes += [2] * (n // 2) + ([1] if n % 2 else [])
    kb.button(text="🧍 К персонажу", callback_data="character")
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()


def heal_kb(player) -> InlineKeyboardMarkup:
    from bot.game import combat
    from bot.game import production as prod
    prods = (player.tavern.products if player.tavern else None) or {}
    kb = InlineKeyboardBuilder()
    if combat.current_hp(player) < combat.max_hp():
        for k in balance.HEAL_VALUES:
            if prods.get(k, 0) > 0:
                g = prod.GOODS[k]
                kb.button(text=f"{g.emoji} {g.name} +{balance.HEAL_VALUES[k]}❤",
                          callback_data=f"heal:{k}")
    kb.button(text="↩️ К охоте", callback_data="hunt")
    kb.adjust(1)
    return kb.as_markup()


def hunt_detail_kb(enemy_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ Охотиться!", callback_data=f"hfight:{enemy_id}")
    kb.button(text="↩️ К зверью", callback_data="hunt")
    kb.adjust(1)
    return kb.as_markup()


def hunt_cta_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏹 На охоту", callback_data="hunt")
    kb.button(text="🏠 К таверне", callback_data="tavern_new")
    kb.adjust(1)
    return kb.as_markup()


def hunt_after_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏹 Ещё охота", callback_data="hunt")
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.button(text="🏠 К таверне", callback_data="tavern_new")
    kb.adjust(1)
    return kb.as_markup()


def citizens_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📜 Хроника города", callback_data="chronicle")
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.adjust(1)
    return kb.as_markup()


def chronicle_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏪 Рынок", callback_data="market")
    kb.button(text="🏛 Расклад сил", callback_data="city")
    kb.button(text="👥 Горожане", callback_data="citizens")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def city_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏪 Рынок", callback_data="market")
    kb.button(text="📜 Хроника города", callback_data="chronicle")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def market_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔨 Аукцион", callback_data="auction")
    kb.button(text="🏛 Расклад сил", callback_data="city")
    kb.button(text="📜 Хроника города", callback_data="chronicle")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def auction_kb(tavern) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if tavern.auction:
        kb.button(text="🔄 Обновить торги", callback_data="auction")
        kb.button(text="🚫 Снять лот", callback_data="auc_cancel")
    else:
        kb.button(text="🛒 Выставить лот", callback_data="auc_new")
    kb.button(text="🏪 Рынок", callback_data="market")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def auction_goods_kb(tavern) -> InlineKeyboardMarkup:
    from bot.game import auction as auc
    from bot.game import production as prod
    kb = InlineKeyboardBuilder()
    for good in auc.sellable_goods(tavern):
        g = prod.GOODS[good]
        stock = (tavern.products or {}).get(good, 0)
        kb.button(text=f"{g.emoji} {g.name} ({stock})", callback_data=f"aucg:{good}")
    kb.button(text="↩️ Назад", callback_data="auction")
    kb.adjust(1)
    return kb.as_markup()


def auction_qty_kb(good: str, stock: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    seen = set()
    for n in balance.AUCTION_QTY_PRESETS:
        q = min(n, stock, balance.AUCTION_QTY_MAX)
        if q > 0 and q not in seen:
            seen.add(q)
            kb.button(text=f"{q} шт", callback_data=f"aucq:{good}:{q}")
    allq = min(stock, balance.AUCTION_QTY_MAX)
    if allq not in seen:
        kb.button(text=f"Всё ({allq})", callback_data=f"aucq:{good}:{allq}")
    kb.button(text="↩️ Назад", callback_data="auc_new")
    kb.adjust(2)
    return kb.as_markup()


def auction_price_kb(good: str, qty: int, prices: list[int]) -> InlineKeyboardMarkup:
    labels = ("По рынку", "Бодрее", "Дорого")
    kb = InlineKeyboardBuilder()
    for idx, (lab, p) in enumerate(zip(labels, prices)):
        kb.button(text=f"{lab} · {p} 🪙/шт", callback_data=f"aucp:{good}:{qty}:{idx}")
    kb.button(text="↩️ Назад", callback_data=f"aucg:{good}")
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
