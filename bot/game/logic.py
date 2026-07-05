"""Игровая логика поверх моделей. Все функции меняют объекты, коммит — снаружи."""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db.models import Player, Tavern
from bot.game import (
    balance, buff, economy, inventory, items, newbie, perks, production, season,
    worldevent,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def expedition_slots(tavern: Tavern) -> int:
    """Число бригад (параллельных вылазок), растёт с уровнем таверны.
    +1 бригада каждые 3 уровня, первая прибавка — уже на 3-м уровне."""
    level = tavern.level if tavern else 1
    return 1 + level // 3


def _exps(player: Player) -> list:
    return list(player.expeditions or [])


@dataclass
class ExpeditionCounts:
    out: int = 0       # в пути
    ready: int = 0     # вернулись, ждут забора
    free: int = 0      # свободные слоты
    total: int = 0     # всего слотов
    next_minutes: int = 0  # до ближайшего возвращения


def expedition_counts(player: Player, tavern: Tavern) -> ExpeditionCounts:
    now = _now()
    exps = _exps(player)
    ready = out = 0
    next_min = 0
    for e in exps:
        left = (datetime.fromisoformat(e["ends_at"]) - now).total_seconds()
        if left > 0:
            out += 1
            m = int(left // 60) + 1
            next_min = m if next_min == 0 else min(next_min, m)
        else:
            ready += 1
    total = expedition_slots(tavern)
    return ExpeditionCounts(
        out=out, ready=ready, free=max(0, total - len(exps)),
        total=total, next_minutes=next_min,
    )


def expedition_goals(player: Player, tavern: Tavern, max_goals: int = 3):
    """Цели, на которые НЕ ХВАТАЕТ ДОБЫВАЕМОГО сырья — подсказка, куда слать бригад.
    Только апгрейд + доступные к стройке пристройки (бригады носят сырьё, не
    компоненты охоты). Возвращает (goals: [(label, {res:дефицит})], total{res:сумма})."""
    from collections import defaultdict
    from bot.game import buildings as bld

    def gatherable_short(cost: dict) -> dict:
        out = {}
        for res, need in cost.items():
            if res in balance.EXPEDITION_YIELD:
                short = need - inventory.get(player, res)
                if short > 0:
                    out[res] = short
        return out

    level = tavern.level if tavern else 1
    region = getattr(player, "region", None)

    def trips(short: dict) -> float:
        """≈ходок бригад до закрытия дефицита (дефицит ÷ добыча за ходку) — мера
        близости к готовности: меньше ходок → ближе достроить → выше приоритет."""
        return sum(q / max(1, balance.expedition_yield(r, level, region))
                   for r, q in short.items())

    # Апгрейд закреплён первым (главная прогрессия), постройки — по близости.
    upgrade_goal = None
    if tavern and level < balance.MAX_LEVEL:
        short = gatherable_short(balance.upgrade_cost(level))
        if short:
            upgrade_goal = (f"🔨 Апгрейд ур.{level + 1}", short)

    building_goals: list = []
    for bid in bld.ORDER:
        b = bld.CATALOG[bid]
        if (bld.is_built(tavern, bid) or bld.missing_requirements(tavern, b)
                or bld.rep_locked(tavern, b)):
            continue
        short = gatherable_short(bld.cost_of(b))   # реальная цена (как экран стройки)
        if short:
            building_goals.append((f"{b.emoji} {b.name}", short))
    building_goals.sort(key=lambda g: trips(g[1]))   # ближайшие к готовности — выше

    ordered = ([upgrade_goal] if upgrade_goal else []) + building_goals
    shown = ordered[:max_goals]
    total: dict = defaultdict(int)
    for _label, short in shown:          # сумма по ПОКАЗАННЫМ целям — чтобы сходилось
        for res, qty in short.items():
            total[res] += qty
    return shown, dict(total)


@dataclass
class ExpeditionStart:
    ok: bool
    reason: str = ""  # no_slot | no_gold
    pay: int = 0


def expedition_quote(player: Player, tavern: Tavern | None) -> tuple[int, float]:
    """РЕАЛЬНЫЕ плата и часы бригады со всеми множителями (снаряга/перки/баф/
    погода/новичок) — единый источник для списания И показа (панель, текст-бот).
    Расхождение показа со списанием — жалоба игрока 02.07."""
    level = tavern.level if tavern else 1
    equipment = getattr(player, "equipment", None)
    pay = max(1, int(balance.worker_pay(level) * items.pay_multiplier(equipment)
                     * perks.expedition_pay_mult(player)
                     * newbie.pay_mult(player)))  # поблажка новичку (с грейс-окном)
    hours = (balance.EXPEDITION_HOURS * items.speed_multiplier(equipment)
             * buff.expedition_speed_mult(player)   # баф «Быстрые ноги»
             * worldevent.exp_speed_mult(player)    # погода (Вёдро/Ненастье)
             * newbie.speed_mult(player))           # поблажка новичку (с грейс-окном)
    return pay, hours


def expedition_gain_quote(player: Player, tavern: Tavern | None, resource: str) -> int:
    """Ожидаемая добыча бригады со ВСЕМИ множителями (без «фарта») — единый
    источник для начисления (claim) и показа в панели."""
    level = tavern.level if tavern else 1
    equipment = getattr(player, "equipment", None)
    amount = balance.expedition_yield(resource, level, player.region)
    return int(amount * items.yield_multiplier(equipment, resource)
               * season.yield_mult(resource) * buff.yield_mult(player)
               * worldevent.harvest_mult(player)
               * newbie.yield_mult(player))


def _passive_rate(player: Player, tavern: Tavern, base_rate: int | None = None) -> float:
    """Полный пассив /ч (float, ДО вычета содержания и округления). ЕДИНЫЙ
    источник для показа (income_rate_quote) и начисления (collect_income) —
    иначе разный порядок округления даёт «показ ≠ капает» (аудит 03.07)."""
    base = tavern.income_rate if base_rate is None else base_rate
    return (base * items.income_multiplier(getattr(player, "equipment", None))
            * perks.passive_mult(player) * buff.gold_mult(player)
            * worldevent.income_mult(player))


def income_rate_quote(player: Player, tavern: Tavern,
                      base_rate: int | None = None) -> int:
    """Реальный пассив «в час» — показ == начислению (единый _passive_rate).
    base_rate — базовая ставка (для превью след. уровня); по умолчанию текущая."""
    r = _passive_rate(player, tavern, base_rate)
    return max(0, int(r - r * balance.WORKER_UPKEEP_PCT))


def start_expedition(player: Player, tavern: Tavern, resource: str) -> ExpeditionStart:
    """Отправить ещё одну бригаду за ресурсом, если есть свободный слот."""
    exps = _exps(player)
    if len(exps) >= expedition_slots(tavern):
        return ExpeditionStart(ok=False, reason="no_slot")

    pay, hours = expedition_quote(player, tavern)
    if player.gold < pay:
        return ExpeditionStart(ok=False, reason="no_gold", pay=pay)

    player.gold -= pay
    exps.append({
        "resource": resource,
        "ends_at": (_now() + timedelta(hours=hours)).isoformat(),
        "notified": False,
    })
    player.expeditions = exps
    return ExpeditionStart(ok=True, pay=pay)


def claim_expeditions(player: Player) -> list[tuple[str, int, bool]]:
    """Забрать всех вернувшихся бригад. Возвращает [(ресурс, кол-во, удача)]."""
    now = _now()
    equipment = getattr(player, "equipment", None)
    kept: list = []
    claimed: list[tuple[str, int, bool]] = []
    for e in _exps(player):
        if (datetime.fromisoformat(e["ends_at"]) - now).total_seconds() > 0:
            kept.append(e)
            continue
        resource = e["resource"]
        amount = expedition_gain_quote(player, player.tavern, resource)
        luck = (items.combat_stats(equipment)["luck"] + perks.luck_bonus(player)
                + buff.luck_bonus(player))  # баф «Фартовый день»
        lucky = random.randint(1, 100) <= balance.lucky_chance(luck)
        if lucky:
            amount *= balance.LUCKY_MULT
        inventory.add(player, resource, amount)
        claimed.append((resource, amount, lucky))
    player.expeditions = kept
    return claimed


@dataclass
class IncomeResult:
    ok: bool
    gold: int = 0
    passive: int = 0
    sales: int = 0
    sold: dict | None = None       # {ключ напитка: продано}
    order: dict | None = None      # {ключ: сколько ХОТЯТ выкупить} — на подтверждение
    spoiled: dict | None = None    # {ключ: скисло} — излишек погреба прокис
    rep_gain: int = 0
    premium_unsold: bool = False   # остался премиум — состоятельных мало
    premium_left: int = 0          # богачей ушло — не было дорогого пойла
    premium_missed: int = 0        # ~упущенная выручка с ушедших богачей
    fair: bool = False             # доход собран во время ярмарки
    skim: int = 0                  # доля, утекшая из-за городской ситуации
    city_label: str = ""           # активная городская ситуация (для показа)
    perk_demand: float = 1.0       # множитель сбыта от перка (купеческая протекция)
    mood_factor: float = 1.0       # множитель спроса от настроения города
    season_demand: float = 1.0     # множитель спроса от сезона/праздника
    season_label: str = ""         # подпись сезона/праздника (для показа)


def collect_income(
    player: Player, tavern: Tavern, demand_mult: float = 1.0
) -> IncomeResult:
    """Пассив капает сразу; СБЫТ гостям — на подтверждение (order). Порча
    погреба идёт независимо от продажи. Спрос гостей считается, но не
    исполняется — игрок сам решает, наливать ли (см. apply_retail)."""
    now = _now()
    since = tavern.last_income_at or now
    hours = min((now - since).total_seconds() / 3600, balance.INCOME_CAP_HOURS)
    if hours <= 0:
        return IncomeResult(ok=False)

    gross = _passive_rate(player, tavern) * hours          # единый источник с показом /ч
    passive = max(0, int(gross - gross * balance.WORKER_UPKEEP_PCT))  # содержание (сток)

    order, premium_unsold, premium_left = _retail_demand(
        tavern, hours, demand_mult, perks.food_mult(player))

    # Порча: излишек сверх вместимости киснет за период (независимо от продажи).
    products = dict(tavern.products or {})
    spoiled = _spoilage(player, tavern, products, hours)
    if spoiled:
        tavern.products = products

    if passive <= 0 and not order and not spoiled:
        return IncomeResult(ok=False)

    player.gold += passive  # пассив — сразу, без подтверждения
    economy.record(player, "passive", passive)
    tavern.last_income_at = now

    # Рычаг 1: богачи пришли, дорогого пойла не нашлось — ушли НЕобслуженными.
    # Это упущенная выручка (а не штраф репутации): показываем ~сколько недозаработал,
    # чтобы мотивировать держать/докупать премиум, без наказания и без фарма.
    premium_missed = premium_left * balance.PREMIUM_MIN_PRICE

    return IncomeResult(
        ok=True, gold=passive, passive=passive, order=order or None,
        spoiled=spoiled or None, premium_unsold=premium_unsold,
        premium_left=premium_left, premium_missed=premium_missed,
    )


def _retail_demand(
    tavern: Tavern, hours: float, demand_mult: float, food_mult: float
) -> tuple[dict, bool, int]:
    """Что гости ХОТЯТ выкупить (без исполнения): (want{ключ:кол}, premium_unsold,
    premium_left). Состоятельные пьют ТОЛЬКО дорогое пойло (≥ PREMIUM_MIN_PRICE);
    кому не хватило — уходят (premium_left). Пьянь — дешёвое (≤порога)."""
    products = tavern.products or {}
    avail = {k: int(v) for k, v in products.items() if v > 0}
    want: dict[str, int] = {}

    def take(key: str, budget: int) -> int:
        n = min(avail.get(key, 0), budget)
        if n > 0:
            avail[key] -= n
            want[key] = want.get(key, 0) + n
        return n

    demand = int(tavern.capacity * balance.DEMAND_PER_CAPACITY * hours * demand_mult)
    share = min(balance.PREMIUM_SHARE_MAX, tavern.reputation / balance.PREMIUM_REP_DIV)
    premium = int(demand * share)
    commoner = demand - premium

    keys = [k for k in products if k in production.DRINKS and products[k] > 0
            and production.npc_tradable(k)]   # эксклюзив зодчих гости не пьют — только биржа
    by_price = sorted(keys, key=lambda k: production.DRINKS[k].price)
    # Состоятельные пьют только «дорогое пойло» (≥ порога), дороже первым. Остаток
    # бюджета (не нашлось дорогого) = богачи, что уйдут недовольными.
    prem_drinks = [k for k in by_price
                   if production.DRINKS[k].price >= balance.PREMIUM_MIN_PRICE]
    for key in reversed(prem_drinks):
        if premium <= 0:
            break
        premium -= take(key, premium)
    premium_left = max(0, premium)
    for key in by_price:
        if commoner <= 0:
            break
        if production.DRINKS[key].price > balance.COMMONER_MAX_PRICE:
            break
        commoner -= take(key, commoner)

    # Еда: тот же принцип сегментации, что и у напитков. Состоятельные едоки
    # берут дорогое (пирог/сыр), простой люд — дешёвое (хлеб) — чтобы дешёвая
    # еда не простаивала вечно за спиной дорогой.
    hunger = int(tavern.capacity * balance.FOOD_DEMAND_PER_CAPACITY * hours
                 * demand_mult * food_mult)
    foods = [k for k in products if k in production.FOODS and products[k] > 0
             and production.npc_tradable(k)]   # эксклюзив зодчих гости не едят — только биржа
    by_food_price = sorted(foods, key=lambda k: production.FOODS[k].price)
    food_premium = int(hunger * share)
    food_common = hunger - food_premium
    for key in reversed(by_food_price):   # состоятельные — дорогое первым
        if food_premium <= 0:
            break
        food_premium -= take(key, food_premium)
    for key in by_food_price:             # простой люд — дешёвое первым
        if food_common <= 0:
            break
        food_common -= take(key, food_common)

    premium_unsold = any(
        avail.get(k, 0) > 0 and production.DRINKS[k].price >= 10 for k in keys
    ) and share < 0.4
    return want, premium_unsold, premium_left


def unit_price(good: str) -> int:
    """Розничная цена за единицу с учётом моды (спрос-событие поднимает ЦЕНУ
    трендового товара). Без моды — обычная цена из каталога."""
    return max(1, round(production.GOODS[good].price * worldevent.good_price_mult(good)))


def assortment_mult(sold: dict | None) -> float:
    """Рычаг 2: бонус за широкое меню — +ASSORTMENT_STEP за каждый ВИД товара,
    РЕАЛЬНО проданный за этот сбыт, сверх первого, до потолка ASSORTMENT_MAX.
    Считаем по проданному (а не по складу), чтобы нельзя было фармить бонус
    1-штучными «жетонами», что лежат непроданными. Стимул держать живое меню."""
    distinct = sum(1 for k, v in (sold or {}).items()
                   if k in production.GOODS and v > 0)
    return min(balance.ASSORTMENT_MAX,
               1.0 + balance.ASSORTMENT_STEP * max(0, distinct - 1))


def retail_total(want: dict | None, player: Player | None = None) -> int:
    """Выручка от сбыта по фиксированным ценам (для показа на подтверждении).
    С игроком — учитывает баф «Бойкая касса», мировое событие и бонус ассортимента,
    чтобы показанная сумма совпала с фактически начисленной в apply_retail."""
    base = sum(int(q) * unit_price(k)
               for k, q in (want or {}).items() if k in production.GOODS)
    if player is None:
        return base
    from bot.game import factions, fgoal
    _msk = (_now().hour + 3) % 24
    return int(base * buff.gold_mult(player) * worldevent.income_mult(player)
               * assortment_mult(want)
               * factions.thief_night_sale_mult(player, _msk)   # ночная скупка воров
               * fgoal.feast_mult())     # городской пир (цель недели взята) — как в apply_retail


def retail_lines(
    want: dict | None, player: Player | None = None
) -> tuple[list[tuple[str, int, int, int]], int]:
    """Разбивка сбыта по товарам: [(key, qty, unit, gold)] + total, где СУММА gold
    строк == retail_total (инвариант «показ = действие»). Голая GOODS.price в строке
    врёт, когда событие мира/буфы двигают кассу: строка показывает свою ДОЛЮ реальной
    выручки. Развёрстка остатка — по-Хэмилтону (крупнейшие остатки получают +1),
    чтобы копейки округления не потерялись и суммы точно сошлись с total."""
    items = [(k, int(q)) for k, q in (want or {}).items()
             if k in production.GOODS and int(q) > 0]
    items.sort(key=lambda kv: -production.GOODS[kv[0]].price)
    total = retail_total(want, player)
    weights = [q * unit_price(k) for k, q in items]
    wsum = sum(weights)
    if not items or wsum <= 0 or total <= 0:
        return [(k, q, unit_price(k), 0) for k, q in items], total
    raw = [total * w / wsum for w in weights]
    gold = [int(x) for x in raw]                       # пол — остаток раздаём ниже
    rem = total - sum(gold)
    for i in sorted(range(len(items)), key=lambda i: raw[i] - gold[i], reverse=True)[:rem]:
        gold[i] += 1                                   # крупнейшие остатки получают +1
    return [(items[i][0], items[i][1],
             max(1, round(gold[i] / items[i][1])) if items[i][1] else gold[i],
             gold[i]) for i in range(len(items))], total


def retail_reason(
    want: dict | None, player: Player | None, base: int, total: int
) -> dict | None:
    """Значок-причина, ПОЧЕМУ касса ≠ сумме привычных цен (base) — чтобы игрок не
    принял разницу за баг. None — если совпадает (±копейки округления). Приоритет —
    активное мировое событие (его и так видно в вестях); иначе общий значок спроса
    (буф кассы / ночная скупка воров / городской пир). Процент — честная НЕТТО-дельта
    от показанного total, а не номинал события (показ = действие)."""
    if base <= 0 or total <= 0:
        return None
    pct = round((total / base - 1) * 100)
    if pct == 0:                                    # различие только в копейках — не шумим
        return None
    sign = f"{'+' if pct > 0 else '−'}{abs(pct)}%"
    e = worldevent.active()
    if e is not None:
        fashion = (e.good_price != 1.0
                   and any(worldevent.good_price_mult(k) != 1.0 for k in (want or {})))
        if fashion:
            return {"emoji": e.emoji, "text": f"{e.name}: товар в моде {sign}"}
        if worldevent.income_mult(player) != 1.0:
            return {"emoji": e.emoji, "text": f"{e.name}: спрос {sign}"}
    return {"emoji": "📉" if pct < 0 else "📈", "text": f"спрос {sign}"}


def add_goods_rep_progress(player: Player, tavern: Tavern, points: int) -> int:
    """Копит «очки молвы» в tavern.rep_progress; каждые REP_PROGRESS_PER_POINT очков →
    +1 репутации игроку и таверне. Остаток сохраняется (мелкие продажи не пропадают).
    Возвращает, сколько единиц репутации начислено этой продажей."""
    if points <= 0:
        return 0
    prog = int(tavern.rep_progress or 0) + points
    gain = prog // balance.REP_PROGRESS_PER_POINT
    tavern.rep_progress = prog - gain * balance.REP_PROGRESS_PER_POINT
    if gain:
        tavern.reputation += gain
        player.reputation += gain
    return gain


def retail_rep_left(tavern: Tavern) -> int:
    """Сколько ещё ПОРЦИЙ гостям до следующей единицы репутации (для прогресс-строки)."""
    left_points = balance.REP_PROGRESS_PER_POINT - int(tavern.rep_progress or 0)
    return max(1, -(-left_points // balance.REP_POINTS_RETAIL))  # ceil-деление


def apply_retail(player: Player, tavern: Tavern, want: dict | None):
    """Исполнить подтверждённый сбыт гостям. Возвращает (sold{}, gold, rep_gain).
    Перепроверяет наличие — продаёт не больше, чем сейчас в погребе."""
    products = dict(tavern.products or {})
    sold: dict[str, int] = {}
    gold = 0
    for key, qty in (want or {}).items():
        if key not in production.GOODS:
            continue
        n = min(int(qty), products.get(key, 0))
        if n > 0:
            products[key] -= n
            sold[key] = n
            gold += n * unit_price(key)
    if not sold:
        return {}, 0, 0
    from bot.game import factions, fgoal
    _msk = (_now().hour + 3) % 24
    gold = int(gold * buff.gold_mult(player) * worldevent.income_mult(player)
               * assortment_mult(sold)    # бонус за число РЕАЛЬНО проданных видов
               * factions.thief_night_sale_mult(player, _msk)   # ночная скупка воров
               * fgoal.feast_mult())      # городской пир: цель недели взята
    fgoal.note("gold_trade", gold)        # оборот двигает цель Лиги
    tavern.products = products
    player.gold += gold
    economy.record(player, "retail", gold)
    total = sum(sold.values())
    rep_gain = add_goods_rep_progress(player, tavern, total * balance.REP_POINTS_RETAIL)
    if perks.has_fame(player):  # знаменитый кабак — доп. слава со сбыта гостям
        tavern.reputation += 1
        player.reputation += 1
        rep_gain += 1
    return sold, gold, rep_gain


def _spoilage(player: Player, tavern: Tavern, products: dict, hours: float) -> dict:
    """Излишек товара сверх вместимости погреба киснет. Мутирует products,
    возвращает {ключ: скисло}. Бьёт пропорционально по запасам.
    Баф «Холодный погреб» режет порчу вдвое."""
    goods = [k for k in production.GOODS if products.get(k, 0) > 0]
    total = sum(products[k] for k in goods)
    cap = balance.cellar_capacity(tavern.capacity)
    if total <= cap:
        return {}
    excess = total - cap
    spoil_total = int(excess * balance.SPOIL_PCT_PER_DAY * hours / 24
                      * buff.spoil_mult(player))
    if spoil_total <= 0:
        return {}
    spoiled: dict[str, int] = {}
    for k in sorted(goods, key=lambda x: -products[x]):
        s = min(products[k], int(round(spoil_total * products[k] / total)))
        if s > 0:
            products[k] -= s
            spoiled[k] = s
    return spoiled


@dataclass
class UpgradeResult:
    ok: bool
    reason: str = ""
    cost: dict | None = None
    new_level: int = 0


def try_upgrade(player: Player, tavern: Tavern) -> UpgradeResult:
    """Улучшение таверны на следующий уровень."""
    if tavern.level >= balance.MAX_LEVEL:
        return UpgradeResult(ok=False, reason="max_level")

    cost = balance.upgrade_cost(tavern.level)
    if not inventory.can_afford(player, cost):
        return UpgradeResult(ok=False, reason="not_enough", cost=cost)

    inventory.pay(player, cost)
    economy.record(player, "upgrade", -int(cost.get("gold", 0)))

    tavern.level += 1
    stats = balance.stats_for_level(tavern.level)
    tavern.capacity = stats["capacity"]
    tavern.comfort = stats["comfort"]
    tavern.income_rate = stats["income_rate"]

    rep = balance.reputation_for_upgrade(tavern.level)
    tavern.reputation += rep
    player.reputation += rep
    player.level = tavern.level

    return UpgradeResult(ok=True, cost=cost, new_level=tavern.level)


def craft_state(player: Player) -> tuple[str, int]:
    """("none"|"active"|"ready", минут до готовности)."""
    if player.craft_item is None or player.craft_ends_at is None:
        return "none", 0
    left = (player.craft_ends_at - _now()).total_seconds()
    if left > 0:
        return "active", int(left // 60) + 1
    return "ready", 0


@dataclass
class CraftStart:
    ok: bool
    reason: str = ""  # busy | unknown | locked | not_enough | max_tier
    item: object = None
    tier: int = 1
    cost: dict | None = None
    hours: int = 0


def next_craft_tier(player: Player, item_id: str) -> int:
    """Какой ярус будет коваться: 1 для новой вещи, +1 для надетой."""
    return items.equipped_tier(getattr(player, "equipment", None), item_id) + 1


def start_craft(player: Player, item_id: str) -> CraftStart:
    """Заказать вещь у мастера. Один заказ за раз.
    Если предмет уже надет — перековка на следующий ярус."""
    state, _ = craft_state(player)
    if state != "none":
        return CraftStart(ok=False, reason="busy")
    item = items.CATALOG.get(item_id)
    if item is None or not item.craftable:   # эксклюзив боссов не куётся
        return CraftStart(ok=False, reason="unknown")
    if items.wonder_gear_locked(player, item_id):   # эксклюзив зодчих — нужен рецепт из Лавки
        return CraftStart(ok=False, reason="locked", item=item)

    tier = next_craft_tier(player, item_id)
    if tier > items.TIER_MAX:
        return CraftStart(ok=False, reason="max_tier", item=item)

    c = items.craft_cost(player, item, tier)   # первая вещь новичка — за четверть
    hours = items.tier_hours(item, tier)
    if not inventory.can_afford(player, c):
        return CraftStart(ok=False, reason="not_enough", item=item,
                          tier=tier, cost=c, hours=hours)

    inventory.pay(player, c)
    economy.record(player, "forge", -int(c.get("gold", 0)))
    from bot.game import newbie as _nb
    _nb.mark_first_craft(player)               # скидка первой ковки сгорает
    player.craft_item = items.make_entry(item_id, tier)
    player.craft_ends_at = _now() + timedelta(hours=hours)
    player.craft_notified = False
    return CraftStart(ok=True, item=item, tier=tier, cost=c, hours=hours)


@dataclass
class CraftClaim:
    ok: bool
    reason: str = ""  # none | not_ready
    minutes_left: int = 0
    item: object = None
    tier: int = 1
    affix: str = ""


AFFIX_CHANCE = {2: 0.25, 3: 0.35}     # шанс аффикса при ковке по ярусам (T1 — без)


def roll_affix(tier: int, rng=None) -> str:
    """Кузнечная удача: вещь T2+ может выйти «с характером» (аффиксом)."""
    import random as _r
    rng = rng or _r
    if rng.random() < AFFIX_CHANCE.get(tier, 0.0):
        return rng.choice(list(items.AFFIXES))
    return ""


def claim_craft(player: Player) -> CraftClaim:
    """Забрать готовую вещь — сразу надевается в свой слот."""
    state, minutes = craft_state(player)
    if state == "none":
        return CraftClaim(ok=False, reason="none")
    if state == "active":
        return CraftClaim(ok=False, reason="not_ready", minutes_left=minutes)

    item_id, tier = items.parse_entry(player.craft_item)
    item = items.CATALOG[item_id]
    equipment = dict(player.equipment or {})
    # Перековка ТОГО ЖЕ предмета на след. ярус — заточка и аффикс ПЕРЕЕЗЖАЮТ (как
    # апгрейд трофеем в рейде, _drop_apply): иначе вложенное в заточку золото (до
    # 2500×ярус за уровень) сгорало бы при каждом апгрейде яруса. Новый предмет в
    # слоте (или пустой слот) — свежий ролл характера (T2+ может выйти с аффиксом).
    prev = equipment.get(item.slot)
    prev_id, _pt, prev_plus, prev_aff = items.parse_full(prev) if prev else (None, 0, 0, "")
    if prev_id == item_id:
        plus, affix = prev_plus, prev_aff
    else:
        plus, affix = 0, roll_affix(tier)
    equipment[item.slot] = items.make_entry(item_id, tier, plus, affix)
    player.equipment = equipment
    player.craft_item = None
    player.craft_ends_at = None
    return CraftClaim(ok=True, item=item, tier=tier, affix=affix)
