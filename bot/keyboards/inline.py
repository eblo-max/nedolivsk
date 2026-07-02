from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Player
from bot.game import balance, logic
from bot.game.balance import REGIONS, RESOURCE_EMOJI, RESOURCE_NAMES

REGION_EMOJI = {"north_wilds": "❄️", "green_valleys": "🌾", "red_wastes": "🏜"}


def create_tavern_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 Создать таверну", callback_data="create_tavern", style="success")
    return kb.as_markup()


def welcome_kb() -> InlineKeyboardMarkup:
    """Хаб на приветственном экране: завести кабак + разделы инфо."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 Завести кабак", callback_data="create_tavern", style="success")
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


def tavern_kb(player: Player, private: bool = True) -> InlineKeyboardMarkup:
    from bot.game import buff, newbie, raid as raidmod, story_state
    from bot.game import invasion as invmod

    kb = InlineKeyboardBuilder()
    sizes: list[int] = []

    # ГЛАВНЫЙ ВХОД в мини-апп (только в личке — web_app группа не принимает).
    # Открываем всем игрокам; внутри доступны готовые разделы (Таверна/Стройка/
    # Персонаж/Вылазки), Торг и Карта пока живут в боте.
    from bot import webapp
    _aurl = webapp.base_url()
    if private and _aurl:
        kb.button(text="🏰 Открыть в приложении", web_app=WebAppInfo(url=f"{_aurl}/app"), style="success")
        sizes.append(1)

    if raidmod.active_id() is not None:  # идёт глобальный рейд-босс — В БОЙ (в мини-апп)!
        _t = "⚔️ РЕЙД-БОСС — В БОЙ!"
        if private and _aurl:           # личка — web_app сразу на экран рейда
            kb.button(text=_t, web_app=WebAppInfo(url=f"{_aurl}/app/?startapp=raid"), style="danger")
        elif _raid_app_btn(kb, _t):     # группа — Direct-Link в мини-апп (?startapp=raid)
            pass
        else:                            # нет короткого имени мини-аппа — чатовая панель (фолбэк)
            kb.button(text=_t, callback_data="raidopen", style="danger")
        sizes.append(1)
    if invmod.gathering_id() is not None:  # идёт сбор на Орду орков — в строй!
        kb.button(text="🪓 ОРДА ОРКОВ — В СТРОЙ!", callback_data="invopen", style="danger")
        sizes.append(1)
    # Web-App кнопки Telegram принимает ТОЛЬКО в личке — в группе панель с такой
    # кнопкой отклоняется целиком (ломала «гг таверна»). Потому карта — лишь в ЛС.
    if private:
        from bot import webapp  # интерактивная карта мира (Mini App) — если хостинг задан
        _murl = webapp.base_url()
        if _murl:
            kb.button(text="🗺 Карта мира", web_app=WebAppInfo(url=f"{_murl}/map"))
            sizes.append(1)
    if player.chat_id is None:  # одиночка — переключатель вестей мира в ЛС
        on = getattr(player, "dm_news", False)
        kb.button(text=f"🌍 Вести мира в ЛС: {'✅' if on else '❌'}",
                  callback_data="dmnews")
        sizes.append(1)
    if newbie.visible(player, player.tavern):  # грамота новосёла (до ур.2)
        ready = newbie.claimable(player, player.tavern)
        kb.button(text="📜 Грамота новосёла 🎁" if ready else "📜 Грамота новосёла",
                  callback_data="newbie", style="success" if ready else None)
        sizes.append(1)
    if buff.offer(player) is not None and buff.active(player) is None:
        kb.button(text="🎁 Бонус дня!", callback_data="bonus", style="success")
        sizes.append(1)
    if story_state.get_retail(player):  # гости ждут решения по сбыту
        kb.button(text="🍺 Гости ждут заказ!", callback_data="retail_open", style="primary")
        sizes.append(1)
    if story_state.get_trade(player):  # купец ждёт ответа по цене
        kb.button(text="🤝 Купец торгуется!", callback_data="trade_open", style="primary")
        sizes.append(1)
    if story_state.get_pending(player):  # незакрытое событие — даём вернуться к нему
        kb.button(text="🔔 Тебя ждёт гость!", callback_data="event_open", style="primary")
        sizes.append(1)

    c = logic.expedition_counts(player, player.tavern)
    if c.ready:
        exp_label = f"🎒 Бригады вернулись ({c.ready})"
    elif c.out:
        exp_label = f"⏳ Бригады в пути ({c.out}/{c.total})"
    else:
        exp_label = "⛏ Отправить бригады"
    # ЯДРО на главной (основная петля): остальное — в подменю «⋯ Ещё», чтобы не
    # пугать новичка простынёй. Контекстные CTA (рейд/бонус/гости…) остаются сверху.
    kb.button(text=exp_label, callback_data="exp_menu")
    kb.button(text="💰 Собрать доход", callback_data="income")
    kb.button(text="🏪 Рынок", callback_data="market")
    kb.button(text="📦 Склад", callback_data="warehouse")
    kb.button(text="🏗 Пристройки", callback_data="buildings")
    kb.button(text="🔨 Улучшить таверну", callback_data="upgrade")
    kb.button(text="⋯ Ещё", callback_data="more")
    kb.adjust(*sizes, 1, 2, 2, 1, 1)
    return kb.as_markup()


def tavern_more_kb(player: Player) -> InlineKeyboardMarkup:
    """Подменю «⋯ Ещё»: второстепенные разделы (не на главной) + назад в таверну."""
    auc = player.tavern.auction or None
    if auc and auc.get("top_bid"):
        auc_label = f"🔨 Торги: {auc['top_bid']}🪙!"
    elif auc:
        auc_label = "🔨 Торги идут"
    else:
        auc_label = "🔨 Аукцион"
    kb = InlineKeyboardBuilder()
    kb.button(text="🧍 Персонаж", callback_data="character")
    kb.button(text=auc_label, callback_data="auction")
    kb.button(text="🌙 Ночная ходка", callback_data="nr:open")
    kb.button(text="🍻 Позвать друга", callback_data="referral")
    kb.button(text="Об игре", callback_data="info", style="danger")
    kb.button(text="🏠 В таверну", callback_data="tavern", style="success")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def nightrun_intro_kb(player: Player, cd: int | None = None) -> InlineKeyboardMarkup:
    from bot.game import nightrun
    if cd is None:
        cd = nightrun.cooldown_left(player)
    kb = InlineKeyboardBuilder()
    if cd <= 0:
        kb.button(text="🌙 Уйти на тракт", callback_data="nr:go", style="primary")
    kb.button(text="🏠 В таверну", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def nightrun_fork_kb(run: dict) -> InlineKeyboardMarkup:
    from bot.game import nightrun
    a, b = nightrun.fork(run)
    L = nightrun.KINDS
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⬅️ {L[a][0]} {L[a][1]}", callback_data=f"nr:pick:{a}")
    kb.button(text=f"➡️ {L[b][0]} {L[b][1]}", callback_data=f"nr:pick:{b}")
    kb.button(text="🏠 Свернуть с добычей", callback_data="nr:bank", style="success")
    kb.adjust(1)
    return kb.as_markup()


def nightrun_wait_kb() -> InlineKeyboardMarkup:
    """Пока висит викторина — даём возможность свернуть (бросить загадку)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Свернуть с добычей", callback_data="nr:bank", style="success")
    kb.adjust(1)
    return kb.as_markup()


def nightrun_meet_kb(run: dict) -> InlineKeyboardMarkup:
    from bot.game import nightrun
    kb = InlineKeyboardBuilder()
    for opt_id, label, _mult, _facs in nightrun.meet_options(run):
        kb.button(text=label, callback_data=f"nr:meet:{opt_id}")
    kb.adjust(1)
    return kb.as_markup()


def nightrun_cross_kb(run: dict) -> InlineKeyboardMarkup:
    from bot.game import nightrun
    kb = InlineKeyboardBuilder()
    if nightrun.can_push(run):
        kb.button(text="⬇️ Глубже в ночь", callback_data="nr:push", style="danger")
    kb.button(text="🏠 Свернуть с добычей", callback_data="nr:bank", style="success")
    kb.adjust(1)
    return kb.as_markup()


def nightrun_after_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В таверну", callback_data="tavern", style="success")
    return kb.as_markup()


def referral_kb(share_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Позвать друга", url=share_url)        # откроет шеринг Telegram
    kb.button(text="🏆 Топ зазывал", callback_data="referrers")
    kb.button(text="🏠 Таверна", callback_data="tavern")
    kb.adjust(1, 2)
    return kb.as_markup()


def referrers_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Назад", callback_data="referral")
    kb.button(text="🏠 Таверна", callback_data="tavern")
    kb.adjust(2)
    return kb.as_markup()


def expedition_menu_kb(player: Player) -> InlineKeyboardMarkup:
    tavern = player.tavern
    level = tavern.level if tavern else 1
    c = logic.expedition_counts(player, tavern)
    kb = InlineKeyboardBuilder()
    sizes: list[int] = []
    if c.ready:
        kb.button(text=f"🎒 Забрать вернувшихся ({c.ready})", callback_data="exp_claim",
                  style="success")
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
    kb.button(text="✅ Улучшить", callback_data="upgrade_confirm", style="success")
    kb.button(text="↩️ Назад", callback_data="tavern")
    kb.adjust(2)
    return kb.as_markup()


def _app_btn(kb, text: str, path: str = "", style: str | None = "success") -> bool:
    """Кнопка, открывающая МИНИ-АПП (WebApp в ЛС). path — под-маршрут (buildings/sorties/
    character). Если домен не задан — кнопку не добавляем (фолбэк на бот-кнопки рядом)."""
    from bot.webapp import base_url
    b = base_url()
    if not b:
        return False
    url = f"{b}/app" + (f"/{path}" if path else "")
    kb.button(text=text, web_app=WebAppInfo(url=url), **({"style": style} if style else {}))
    return True


def story_push_kb() -> InlineKeyboardMarkup:
    """Ретеншн-пуш «у стойки гость» — открыть таверну в мини-аппе."""
    kb = InlineKeyboardBuilder()
    if not _app_btn(kb, "🍺 Загляни в таверну"):
        kb.button(text="🍺 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def notif_teaser_kb() -> InlineKeyboardMarkup:
    """Тизер «весть в таверну» — открыть раздел «Уведомления» в мини-аппе (WebApp в ЛС)."""
    from bot.webapp import base_url
    kb = InlineKeyboardBuilder()
    b = base_url()
    if b:
        kb.button(text="🔔 Открыть уведомления",
                  web_app=WebAppInfo(url=f"{b}/app/?startapp=notif"))
    else:
        kb.button(text="🍺 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def urgent_dm_kb(kind: str) -> InlineKeyboardMarkup:
    """Срочная весть в личке (рейд/орда) — красная кнопка сразу в бой.
    Рейд живёт в мини-аппе (?startapp=raid), орда — чатовый экран (invopen)."""
    from bot.webapp import base_url
    kb = InlineKeyboardBuilder()
    b = base_url()
    if kind == "raid" and b:
        kb.button(text="⚔️ В БОЙ — открыть в игре",
                  web_app=WebAppInfo(url=f"{b}/app/?startapp=raid"), style="danger")
    elif kind == "invasion":
        kb.button(text="🪓 ОРДА ОРКОВ — В СТРОЙ!", callback_data="invopen", style="danger")
    else:
        kb.button(text="🍺 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def claim_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _app_btn(kb, "🎒 Забрать — в приложении")          # → мини-апп (Таверна)
    kb.button(text="🎒 Забрать добычу", callback_data="exp_claim", style="success")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def trade_kb(offer: dict) -> InlineKeyboardMarkup:
    p = offer["prices"]
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🪙 Дёшево · {p[0]}/шт", callback_data="trd:0")
    kb.button(text=f"💰 По рынку · {p[1]}/шт", callback_data="trd:1")
    kb.button(text=f"🤑 Дорого · {p[2]}/шт", callback_data="trd:2")
    kb.button(text="🚪 Не продавать", callback_data="trd:no", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def trade_counter_kb(counter: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🤝 Идёт · {counter}/шт", callback_data="trd:ok", style="success")
    kb.button(text="💬 Дожать ещё", callback_data="trd:push")
    kb.button(text="🚪 Послать", callback_data="trd:no", style="danger")
    kb.adjust(1)
    return kb.as_markup()


def loot_kb(drop_id: int) -> InlineKeyboardMarkup:
    """Кнопка подкидыша — кто первый нажал, тот подобрал (публичная)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🤲 Поднять!", callback_data=f"loot:{drop_id}", style="success")
    return kb.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ К таверне", callback_data="tavern")
    return kb.as_markup()


def idle_nudge_kb() -> InlineKeyboardMarkup:
    """Кнопка возвращения в игру из напоминания о простое."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🍺 Скорей в кабак!", callback_data="tavern", style="success")
    return kb.as_markup()


def onboard_nudge_kb() -> InlineKeyboardMarkup:
    """Кнопка «завести кабак» из дожима онбординга."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏗 Завести кабак", callback_data="create_tavern", style="success")
    return kb.as_markup()


def warehouse_kb() -> InlineKeyboardMarkup:
    """Склад: вход в лавку скупщика + назад."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Лавка скупщика", callback_data="shop")
    kb.button(text="🏠 Таверна", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def shop_kb(player) -> InlineKeyboardMarkup:
    """Лавка скупщика: сырьё по цене за единицу → выбор ресурса."""
    from bot.game import balance as b
    from bot.game import shop
    kb = InlineKeyboardBuilder()
    for res in shop.sellable():
        emoji = b.RESOURCE_EMOJI.get(res, "📦")
        name = b.RESOURCE_NAMES.get(res, res)
        kb.button(text=f"{emoji} {name} · {shop.price(res)}", callback_data=f"shopbuy:{res}")
    kb.button(text="📦 Склад", callback_data="warehouse")
    kb.button(text="🏠 Таверна", callback_data="tavern")
    kb.adjust(2)
    return kb.as_markup()


def shop_resource_kb(res: str, player) -> InlineKeyboardMarkup:
    """Выбор количества покупки одного ресурса (пресеты + «макс»)."""
    from bot.game import balance as b
    from bot.game import shop
    kb = InlineKeyboardBuilder()
    mx = shop.max_affordable(player, res)
    for q in b.SHOP_QTY_PRESETS:
        if q <= mx:
            kb.button(text=f"+{q}", callback_data=f"shopq:{res}:{q}")
    if mx > 0:
        kb.button(text=f"Макс ({mx})", callback_data=f"shopq:{res}:{mx}")
    kb.button(text="↩️ В лавку", callback_data="shop")
    kb.adjust(3, 1)
    return kb.as_markup()


def upgrade_short_kb() -> InlineKeyboardMarkup:
    """Не хватило на апгрейд — предложить докупить сырьё в лавке за золото."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Докупить и улучшить", callback_data="shopfill", style="success")
    kb.button(text="↩️ Назад", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def bonus_push_kb() -> InlineKeyboardMarkup:
    """Кнопка из утреннего пуша — сразу к экрану бонуса дня."""
    kb = InlineKeyboardBuilder()
    _app_btn(kb, "🎁 Забрать — в приложении")
    kb.button(text="🎁 Забрать опохмел", callback_data="bonus", style="success")
    kb.adjust(1)
    return kb.as_markup()


def newbie_kb(player) -> InlineKeyboardMarkup:
    """Экран грамоты новосёла: забрать готовые награды (если есть) + назад."""
    from bot.game import newbie
    kb = InlineKeyboardBuilder()
    if newbie.claimable(player, player.tavern):
        kb.button(text="🎁 Забрать награды", callback_data="newbie_claim",
                  style="success")
    kb.button(text="↩️ К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def bonus_kb(player) -> InlineKeyboardMarkup:
    """Экран ежедневного бонуса: активировать (если есть и не занят) + назад."""
    from bot.game import buff

    kb = InlineKeyboardBuilder()
    if buff.active(player) is None and buff.offer(player) is not None:
        kb.button(text=f"✨ Активировать ({buff.BUFF_HOURS} ч)",
                  callback_data="bonus_go", style="success")
    kb.button(text="↩️ К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def retail_kb(total: int) -> InlineKeyboardMarkup:
    """Подтверждение сбыта гостям: налить (продать) или придержать товар."""
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🍺 Налить гостям · +{total} 🪙", callback_data="retail_sell",
              style="success")
    kb.button(text="🤚 Придержать товар", callback_data="retail_hold")
    kb.adjust(1)
    return kb.as_markup()


def character_kb(craft_ready: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if craft_ready:
        kb.button(text="🎁 Забрать у мастера", callback_data="craft_claim", style="success")
    kb.button(text="⚒ Кузница", callback_data="forge")
    kb.button(text="🏹 Охота (скоро)", callback_data="hunt")
    kb.button(text="👥 Горожане", callback_data="citizens")
    kb.button(text="🏠 К таверне", callback_data="tavern_new")
    kb.adjust(1)
    return kb.as_markup()


def hunt_menu_kb(player) -> InlineKeyboardMarkup:
    from bot.game import combat
    kb = InlineKeyboardBuilder()
    sizes = []
    if combat.can_heal(player):
        kb.button(text="🍖 Подлечиться", callback_data="healmenu", style="success")
        sizes.append(1)
    beasts = combat.huntable(getattr(player, "region", None))   # +зверь своего региона
    for e in beasts:
        kb.button(text=f"{e.emoji} {e.name}", callback_data=f"hbeast:{e.id}")
    n = len(beasts)
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
    if combat.current_hp(player) < combat.max_hp(player):
        for k in balance.HEAL_VALUES:
            if prods.get(k, 0) > 0:
                g = prod.GOODS[k]
                kb.button(text=f"{g.emoji} {g.name} +{combat.heal_amount(player, k)}❤",
                          callback_data=f"heal:{k}", style="success")
    kb.button(text="↩️ К охоте", callback_data="hunt")
    kb.adjust(1)
    return kb.as_markup()


def hunt_detail_kb(enemy_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ Охотиться!", callback_data=f"hfight:{enemy_id}", style="danger")
    kb.button(text="↩️ К зверью", callback_data="hunt")
    kb.adjust(1)
    return kb.as_markup()


def hunt_cta_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _app_btn(kb, "🏹 На охоту — в приложении", "sorties")
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
    sizes = []
    if tavern.auction:
        kb.button(text="🔄 Обновить", callback_data="auction")
        kb.button(text="🚫 Снять лот", callback_data="auc_cancel", style="danger")
        sizes.append(2)
    else:
        kb.button(text="🔨 Аукцион NPC", callback_data="auc_new", style="success")
        sizes.append(1)
    # Городская биржа (P2P): обе стороны ордербука — короткие подписи
    kb.button(text="🛒 Купить", callback_data="bourse:0:all")
    kb.button(text="📥 Заявки", callback_data="blb:0:all")
    kb.button(text="📤 Продать", callback_data="bsell", style="success")
    kb.button(text="📣 Куплю", callback_data="bbidnew", style="success")
    kb.button(text="📦 Мои лоты", callback_data="bmine")
    kb.button(text="📊 Цены", callback_data="bprices")
    kb.button(text="🏆 Продавцы", callback_data="sellers")
    kb.button(text="🏪 Рынок", callback_data="market")
    kb.button(text="🏠 Таверна", callback_data="tavern")
    kb.adjust(*sizes, 2, 2, 2, 2, 1)
    return kb.as_markup()


def bourse_prices_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="bprices", style="success")
    kb.button(text="↩️ К торгам", callback_data="auction")
    kb.adjust(1)
    return kb.as_markup()


def sellers_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="sellers", style="success")
    kb.button(text="↩️ К торгам", callback_data="auction")
    kb.adjust(1)
    return kb.as_markup()


def _back_to_auction(kb: InlineKeyboardBuilder) -> None:
    kb.button(text="↩️ К торгам", callback_data="auction")


CAT_LABEL = {"all": "Всё", "drink": "Напитки", "food": "Еда"}
_CAT_NEXT = {"all": "drink", "drink": "food", "food": "all"}


def _good_emoji(good: str) -> str:
    from bot.game import production as prod
    g = prod.GOODS.get(good)
    return g.emoji if g else "📦"


def bourse_list_kb(orders, page: int, total: int, cat: str,
                   side: str) -> InlineKeyboardMarkup:
    """Список лотов одной стороны. side='sell' (купить) / 'buy' (заявки куплю)."""
    list_cb = "bourse" if side == "sell" else "blb"
    item_cb = "bord" if side == "sell" else "bbid"
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🔎 {CAT_LABEL[cat]}",
              callback_data=f"{list_cb}:0:{_CAT_NEXT[cat]}")
    for o in orders:
        kb.button(text=f"{_good_emoji(o.good)} {o.qty}шт × {o.unit_price}🪙",
                  callback_data=f"{item_cb}:{o.id}")
    sizes = [1] + [1] * len(orders)
    nav = []
    if page > 0:
        kb.button(text="◀️", callback_data=f"{list_cb}:{page - 1}:{cat}")
        nav.append(1)
    if (page + 1) * balance.BOURSE_PAGE < total:
        kb.button(text="▶️", callback_data=f"{list_cb}:{page + 1}:{cat}")
        nav.append(1)
    _back_to_auction(kb)
    kb.adjust(*sizes, len(nav) if nav else 1, 1)
    return kb.as_markup()


def bourse_order_kb(order, player) -> InlineKeyboardMarkup:
    """Карточка лота ПРОДАЖИ: одна кнопка — ввести количество для покупки."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Купить", callback_data=f"bbuyq:{order.id}", style="success")
    kb.button(text="↩️ К лотам", callback_data="bourse:0:all")
    kb.adjust(1)
    return kb.as_markup()


def bourse_bid_kb(order, tavern) -> InlineKeyboardMarkup:
    """Карточка ЗАЯВКИ «куплю»: одна кнопка — ввести количество для продажи."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Продать", callback_data=f"bfillq:{order.id}", style="success")
    kb.button(text="↩️ К заявкам", callback_data="blb:0:all")
    kb.adjust(1)
    return kb.as_markup()


def bourse_cancel_kb() -> InlineKeyboardMarkup:
    """Отмена свободного ввода количества/цены."""
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Отмена", callback_data="binputcancel")
    return kb.as_markup()


def bourse_sell_goods_kb(tavern) -> InlineKeyboardMarkup:
    from bot.game import bourse
    from bot.game import production as prod
    kb = InlineKeyboardBuilder()
    for good in bourse.sellable_goods(tavern):
        g = prod.GOODS[good]
        stock = (tavern.products or {}).get(good, 0)
        kb.button(text=f"{g.emoji} {g.name} ({stock})", callback_data=f"bsg:{good}")
    _back_to_auction(kb)
    kb.adjust(1)
    return kb.as_markup()


def bourse_bid_goods_kb() -> InlineKeyboardMarkup:
    """Что хочешь купить — любой товар каталога."""
    from bot.game import production as prod
    kb = InlineKeyboardBuilder()
    for good, g in prod.GOODS.items():
        kb.button(text=f"{g.emoji} {g.name}", callback_data=f"bbg:{good}")
    _back_to_auction(kb)
    kb.adjust(2)
    return kb.as_markup()


def bourse_mine_kb(orders) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        tag = "📤" if o.side == "sell" else "📣"
        kb.button(text=f"🚫 {tag} {_good_emoji(o.good)} {o.qty}×{o.unit_price}🪙",
                  callback_data=f"bcancel:{o.id}", style="danger")
    _back_to_auction(kb)
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
    for idx, (lab, p) in enumerate(zip(labels, prices, strict=False)):
        kb.button(text=f"{lab} · {p} 🪙/шт", callback_data=f"aucp:{good}:{qty}:{idx}")
    kb.button(text="↩️ Назад", callback_data=f"aucg:{good}")
    kb.adjust(1)
    return kb.as_markup()


def forge_kb(player: Player | None = None) -> InlineKeyboardMarkup:
    from bot.game.items import CATALOG, REGION_GEAR, TIER_STARS, equipped_tier

    equipment = getattr(player, "equipment", None) if player else None
    region = getattr(player, "region", None) if player else None
    kb = InlineKeyboardBuilder()
    for item in CATALOG.values():     # сперва то, что КУЁТСЯ
        if not item.craftable:
            continue
        if item.id in REGION_GEAR and REGION_GEAR[item.id] != region:
            continue                  # чужой региональный пояс — скрафтить нельзя, скрываем
        tier = equipped_tier(equipment, item.id)
        label = f"{item.name} {TIER_STARS[tier]}" if tier else item.name
        kb.button(text=label, callback_data=f"forge_item:{item.id}")
    for item in CATALOG.values():     # боссовый трофей — не куётся, но если он ЕСТЬ, покажем
        if item.craftable:
            continue
        tier = equipped_tier(equipment, item.id)
        if not tier:                  # нет у игрока — не маячим (увидит, когда выпадет)
            continue
        kb.button(text=f"🏆 {item.name} {TIER_STARS[tier]}", callback_data=f"forge_item:{item.id}")
    kb.button(text="↩️ Назад", callback_data="character")
    kb.adjust(2)
    return kb.as_markup()


def forge_item_kb(item_id: str, maxed: bool = False,
                  craftable: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if craftable and not maxed:       # боссовый трофей не куётся — кнопки заказа нет
        kb.button(text="⚒ Заказать", callback_data=f"forge_make:{item_id}", style="success")
    kb.button(text="↩️ В кузницу", callback_data="forge")
    kb.adjust(2)
    return kb.as_markup()


def craft_claim_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _app_btn(kb, "🎁 Забрать — в приложении", "character")
    kb.button(text="🎁 Забрать вещь", callback_data="craft_claim", style="success")
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
        kb.button(text="🏗 Построить", callback_data=f"build_make:{building.id}",
                  style="success")
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
    _app_btn(kb, "🏗 Пристройки — в приложении", "buildings")
    kb.button(text="🏗 Пристройки", callback_data="buildings")
    kb.button(text="🏠 К таверне", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


def production_kb(player, tavern, building) -> InlineKeyboardMarkup:
    from bot.game import production as prod

    kb = InlineKeyboardBuilder()
    state, _ = prod.state(tavern, building.id)
    bid = building.id
    if bid in prod.GRIND:  # мельница/горн: сырьё → полуфабрикат в инвентарь
        if state == "ready":
            kb.button(text="📦 Забрать", callback_data=f"prod_claim:{bid}",
                      style="success")
        elif state == "none":
            for recipe in prod.GRIND[bid]:
                kb.button(
                    text=f"{balance.GOODS_EMOJI[recipe]} {balance.GOODS_NAMES[recipe]}",
                    callback_data=f"grind:{bid}:{recipe}")
        kb.button(text="↩️ К пристройкам", callback_data="buildings")
        kb.adjust(1)
        return kb.as_markup()
    if bid in prod.RECIPES:  # пекарня/коптильня/сыроварня: вход → товар в погреб
        if state == "ready":
            kb.button(text="🍽 Забрать в погреб", callback_data=f"prod_claim:{bid}",
                      style="success")
        elif state == "none":
            for recipe in prod.RECIPES[bid]:
                g = prod.GOODS[recipe]
                kb.button(text=f"{g.emoji} {g.name}", callback_data=f"rcp:{bid}:{recipe}")
        kb.button(text="↩️ К пристройкам", callback_data="buildings")
        kb.adjust(1)
        return kb.as_markup()
    if building.id == "brewery":
        phase, _ = prod.brew_phase(tavern)
        if phase == "ready":
            kb.button(text="🍺 Разлить в погреб", callback_data="prod_claim:brewery",
                      style="success")
            if int(tavern.production["brewery"]["tier"]) < 3:
                kb.button(text="🛢 Выдержать (рискнуть)", callback_data="brew_age",
                          style="danger")
        elif phase in ("ripe", "overripe"):
            kb.button(text="🍺 Разлить выдержку", callback_data="prod_claim:brewery",
                      style="success")
        elif phase == "empty":
            kb.button(text="★ Эль", callback_data="brew:1")
            kb.button(text="★★ Светлое", callback_data="brew:2")
            kb.button(text="★★★ Праздничное", callback_data="brew:3")
    elif building.id == "meadery":
        if state == "ready":
            kb.button(text="🍶 Разлить в погреб", callback_data="prod_claim:meadery",
                      style="success")
        elif state == "none":
            kb.button(text="🍶 Медовуха", callback_data="meadery:mead")
            kb.button(text="🌿 Сбитень", callback_data="meadery:sbiten")
    elif building.id == "kitchen":
        if state == "ready":
            kb.button(text="🍖 Забрать в кладовую", callback_data="prod_claim:kitchen",
                      style="success")
        elif state == "none":
            kb.button(text="🍖 Жаркое", callback_data="kitchen:roast")
    elif building.id == "winery":
        if state == "ready":
            kb.button(text="🍷 Разлить в погреб", callback_data="prod_claim:winery",
                      style="success")
        elif state == "none":
            kb.button(text="🍷 Вино", callback_data="winery:wine")
    kb.button(text="↩️ К пристройкам", callback_data="buildings")
    kb.adjust(1)
    return kb.as_markup()


def _raid_app_btn(kb: InlineKeyboardBuilder, text: str) -> bool:
    """Кнопка-дип-линк В МИНИ-АПП на экран рейда (Direct-Link ?startapp=raid).
    Работает и в группах, и в личке. True — добавлена; False — нет короткого имени
    мини-аппа (webapp_short_name), тогда вызывающий ставит чатовый фолбэк."""
    from bot.config import settings
    short = (getattr(settings, "webapp_short_name", "") or "").strip()
    if short and _BOT_USERNAME:
        kb.button(text=text, url=f"https://t.me/{_BOT_USERNAME}/{short}?startapp=raid")
        return True
    return False


def raid_gather_kb(raid_id: int) -> InlineKeyboardMarkup:
    """Фаза сбора: вход В МИНИ-АПП (запись/бой — только там). Фолбэк — чатовая кнопка."""
    kb = InlineKeyboardBuilder()
    if not _raid_app_btn(kb, "⚔️ В БОЙ — открыть в игре"):
        kb.button(text="⚔️ Присоединиться", callback_data=f"raidjoin:{raid_id}", style="success")
        kb.button(text="🔄 Обновить", callback_data=f"raidref:{raid_id}")
    kb.adjust(1)
    return kb.as_markup()


def raid_kb(raid_id: int) -> InlineKeyboardMarkup:
    """Фаза битвы: вход В МИНИ-АПП (бить там). Фолбэк — чатовая кнопка."""
    kb = InlineKeyboardBuilder()
    if not _raid_app_btn(kb, "⚔️ БИТЬ — открыть в игре"):
        kb.button(text="⚔️ Бить", callback_data=f"raidhit:{raid_id}", style="danger")
        kb.button(text="🔄 Обновить", callback_data=f"raidref:{raid_id}")
    kb.adjust(1)
    return kb.as_markup()


def invasion_gather_kb(inv_id: int) -> InlineKeyboardMarkup:
    """Фаза сбора ивента «Орда орков»: поднять войско таверны (публичная кнопка)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ Поднять войско", callback_data=f"invjoin:{inv_id}", style="danger")
    kb.button(text="🔄 Обновить", callback_data=f"invref:{inv_id}")
    kb.adjust(1, 1)
    return kb.as_markup()


def invasion_open_kb(inv_id: int, private: bool, already: bool) -> InlineKeyboardMarkup:
    """Экран «в строй» из меню таверны: запись + карта (бой) + назад."""
    from bot.config import settings
    from bot.webapp import base_url
    kb = InlineKeyboardBuilder()
    if not already:
        kb.button(text="⚔️ Поднять войско", callback_data=f"invjoin:{inv_id}", style="danger")
    b = base_url()
    if b and private:
        kb.button(text="🗺 На карту — следить за боем", web_app=WebAppInfo(url=f"{b}/map"))
    elif b:
        short = (getattr(settings, "webapp_short_name", "") or "").strip()
        if short and _BOT_USERNAME:
            kb.button(text="🗺 На карту — следить за боем",
                      url=f"https://t.me/{_BOT_USERNAME}/{short}?startapp=map")
    kb.button(text="🏠 В таверну", callback_data="tavern")
    kb.adjust(1)
    return kb.as_markup()


# Имя бота — для Direct-Link Mini App URL в анонсах (ставится на старте из get_me).
_BOT_USERNAME = ""


def set_bot_username(username: str) -> None:
    global _BOT_USERNAME
    _BOT_USERNAME = (username or "").lstrip("@")


def get_bot_username() -> str:
    """Текущее имя бота (для ссылок t.me/<bot>?start=… в мини-аппе)."""
    return _BOT_USERNAME


def world_map_kb(private: bool) -> InlineKeyboardMarkup | None:
    """Кнопка «Открыть интерактивную карту»: в личке — web_app (работает сразу);
    в группе — url на Direct-Link Mini App (если настроен webapp_short_name + имя
    бота), иначе None (web_app в группах Telegram не работает)."""
    from bot.config import settings
    from bot.webapp import base_url
    b = base_url()
    if not b:
        return None
    kb = InlineKeyboardBuilder()
    if private:
        from aiogram.types import WebAppInfo
        kb.button(text="🗺 Открыть карту мира", web_app=WebAppInfo(url=b + "/map"))
        return kb.as_markup()
    short = (getattr(settings, "webapp_short_name", "") or "").strip()
    if short and _BOT_USERNAME:
        kb.button(text="🗺 Открыть карту мира",
                  url=f"https://t.me/{_BOT_USERNAME}/{short}?startapp=map")
        return kb.as_markup()
    return None


def invasion_map_dm_kb(map_url: str) -> InlineKeyboardMarkup:
    """Личка-кнопка: web_app открывает карту прямо в Telegram (тест/админ/пуш)."""
    from aiogram.types import WebAppInfo
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ К ОРДЕ — открыть карту", web_app=WebAppInfo(url=map_url), style="danger")
    return kb.as_markup()


def invasion_announce_kb(inv_id: int) -> InlineKeyboardMarkup:
    """Кнопка анонса орды. Если настроен Direct-Link Mini App (webapp_short_name +
    имя бота) — красная url-кнопка ОТКРЫВАЕТ КАРТУ на боссе (вся регистрация там).
    Иначе фолбэк: обычная запись прямо в чате (callback)."""
    from bot.config import settings
    short = (getattr(settings, "webapp_short_name", "") or "").strip()
    kb = InlineKeyboardBuilder()
    if short and _BOT_USERNAME:
        kb.button(text="⚔️ К ОРДЕ — открыть карту", style="danger",
                  url=f"https://t.me/{_BOT_USERNAME}/{short}?startapp=inv{inv_id}")
        kb.adjust(1)
        return kb.as_markup()
    kb.button(text="⚔️ Поднять войско", callback_data=f"invjoin:{inv_id}", style="danger")
    kb.button(text="🔄 Обновить", callback_data=f"invref:{inv_id}")
    kb.adjust(1, 1)
    return kb.as_markup()
