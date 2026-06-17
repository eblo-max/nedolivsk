"""Монте-Карло симулятор экономики и баланса «Недоливска».

Считает на РЕАЛЬНЫХ функциях игры (bot.game.*), а не на перерисованной модели:
вылазки, производство всех пристроек, розница с сегментацией гостей, пассивный
доход, охота (реальный бой), апгрейды, крафт снаряги, лавка, сбыт сырья.

Подход — «таблица-как-код» + Монте-Карло (как балансят F2P/MMO; см. Lehdonvirta
«Virtual Economies» — учёт КРАНОВ и СТОКОВ золота, и Machinations — потоки
ресурсов). Запуск:

    python scripts/sim_economy.py                 # полный отчёт
    python scripts/sim_economy.py --players 200 --days 45
    python scripts/sim_economy.py --quick          # быстрый прогон

Артефакт: scripts/sim_out/report.md (+ краткая сводка в stdout).
"""
from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from bot.game import balance, buildings, combat, items, logic, production, raid, shop

OUT = Path(__file__).resolve().parent / "sim_out"


# ════════════════════════════════════════════════════════════════════════
#  Утилиты
# ════════════════════════════════════════════════════════════════════════
def pct(values, p):
    return float(np.percentile(values, p)) if values else 0.0


def spark(series):
    """ASCII-спарклайн ряда (8 уровней)."""
    bars = "▁▂▃▄▅▆▇█"
    if not series:
        return ""
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1
    return "".join(bars[min(7, int((v - lo) / rng * 7))] for v in series)


def unit_price_sim(key: str) -> int:
    """Розничная цена товара (без событий моды — нейтральный мир)."""
    return production.GOODS[key].price


# ════════════════════════════════════════════════════════════════════════
#  Производство: единый диспетчер на реальные функции игры
#  building -> что варит, сколько входов/выхода/часов, куда кладёт (cellar/inv)
# ════════════════════════════════════════════════════════════════════════
def prod_spec(building: str, recipe: str, level: int):
    """(inputs{}, out_key, out_qty, hours, dest)."""
    if building == "brewery":
        t = int(recipe)
        return (production.brew_inputs(t, level), production.ale_key(t),
                production.brew_output(t, level), production.brew_hours(t), "cellar")
    if building == "mill":
        return (production.grind_inputs("mill", recipe, level), recipe,
                production.grind_output("mill", recipe, level),
                production.grind_minutes("mill", recipe) / 60, "inv")
    if building == "smelter":
        return (production.grind_inputs("smelter", "ingot", level), "ingot",
                production.grind_output("smelter", "ingot", level),
                production.grind_minutes("smelter", "ingot") / 60, "inv")
    if building == "kitchen":
        return (production.kitchen_inputs(recipe, level), recipe,
                production.kitchen_output(recipe, level),
                production.kitchen_hours(recipe), "cellar")
    if building == "winery":
        return (production.winery_inputs(recipe, level), recipe,
                production.winery_output(recipe, level),
                production.winery_hours(recipe), "cellar")
    if building == "meadery":
        return (production.meadery_inputs(recipe, level), recipe,
                production.meadery_output(recipe, level),
                production.meadery_hours(recipe), "cellar")
    if building in production.RECIPES:  # bakery/smokehouse/dairy
        return (production.recipe_inputs(building, recipe, level), recipe,
                production.recipe_output(building, recipe, level),
                production.recipe_hours(building, recipe), "cellar")
    raise ValueError(building)


# ════════════════════════════════════════════════════════════════════════
#  Стратегии (архетипы игроков)
# ════════════════════════════════════════════════════════════════════════
@dataclass
class Strategy:
    name: str
    sessions_per_day: int            # сколько раз в день заходит в бота
    # производственный план: список (building, recipe) — что держит запущенным
    plan: list = field(default_factory=list)
    build_order: list = field(default_factory=list)  # какие пристройки строит
    expedition_focus: list = field(default_factory=list)  # за каким сырьём шлёт бригады
    hunt: bool = False
    hunt_min_wr: int = 70            # порог винрейта, при котором идёт в бой (%)
    craft_order: list = field(default_factory=list)  # очередь ковки снаряги
    upgrade: bool = True             # тянет ли уровни таверны
    upgrade_reserve: int = 0         # сколько золота держать в резерве, не тратя на апгрейд
    use_shop: bool = False           # докупает ли сырьё в лавке под нужды
    sell_raw: bool = False           # сбывает ли излишек сырья купцу
    sell_goods_surplus: bool = True  # сбывает ли излишек товара (опт), что не выпили гости


def _drink_plan(tier):
    """Цепочка под эль данного яруса: мельница (солод) + пивоварня."""
    return [("mill", "malt"), ("brewery", str(tier))]


# Корзина вылазок включает и апгрейд-сырьё (wood/grain/hops, с ур.5 — stone),
# и сырьё под производство стратегии — как реальный игрок, что юлит между нуждами.
STRATEGIES = {
    "farmer": Strategy(
        name="Фармер-доходник", sessions_per_day=4,
        plan=_drink_plan(1), build_order=["mill", "brewery"],
        expedition_focus=["wood", "grain", "hops", "water"], upgrade=True),
    "premium": Strategy(
        name="Крафтер-премиум", sessions_per_day=4,
        plan=[("winery", "wine"), ("kitchen", "roast")],
        build_order=["kitchen", "winery"],
        expedition_focus=["wood", "grain", "hops", "berries", "honey", "game", "herbs", "water"],
        upgrade=True),
    "trader": Strategy(
        name="Торгаш-сырьевик", sessions_per_day=5,
        plan=[], build_order=[],
        expedition_focus=["ore", "honey", "game", "wood", "grain", "hops"],
        upgrade=True, sell_raw=True),
    "raider": Strategy(
        name="Рейдер-охотник", sessions_per_day=5,
        plan=[("smelter", "ingot")], build_order=["smelter"],
        expedition_focus=["wood", "grain", "hops", "ore"],
        hunt=True, hunt_min_wr=65,
        craft_order=["master_axe", "fartuk", "fang_cleaver", "fur_coat",
                     "swift_boots", "kovsh", "oak_shield", "leather_cap"],
        upgrade=True),
    "builder": Strategy(
        name="Строитель-рашер", sessions_per_day=4,
        plan=_drink_plan(1), build_order=["mill", "brewery", "kitchen"],
        expedition_focus=["wood", "grain", "hops", "clay", "stone", "ore"],
        upgrade=True, upgrade_reserve=0),
    "shopper": Strategy(
        name="Лавочник (всё за золото)", sessions_per_day=4,
        plan=_drink_plan(1), build_order=["mill", "brewery"],
        expedition_focus=["grain", "hops", "water"],
        upgrade=True, use_shop=True),
    "casual": Strategy(
        name="Казуал (раз в день)", sessions_per_day=1,
        plan=_drink_plan(1), build_order=["mill", "brewery"],
        expedition_focus=["wood", "grain", "hops"], upgrade=True),
    "optimizer": Strategy(
        name="Гиперактив (8 заходов/день)", sessions_per_day=8,
        plan=[("mill", "malt"), ("brewery", "1"), ("kitchen", "roast")],
        build_order=["mill", "brewery", "kitchen"],
        expedition_focus=["wood", "grain", "hops", "water", "game", "herbs"],
        hunt=True, hunt_min_wr=60,
        craft_order=["kruzhka", "leather_cap", "rooster_talisman"],
        upgrade=True, use_shop=True),
}


# ════════════════════════════════════════════════════════════════════════
#  Состояние игрока в симуляции
# ════════════════════════════════════════════════════════════════════════
class SimPlayer:
    def __init__(self, region: str):
        self.gold = 200            # подъёмные новичка примерно
        self.region = region
        self.level = 1
        self.reputation = 0
        self.rep_progress = 0
        self.hp = float(balance.BASE_HP)
        self.equipment: dict[str, str] = {}
        self.inventory: dict[str, int] = dict(balance.STARTING_INVENTORY)
        self.products: dict[str, int] = {}
        self.buildings: list[str] = []
        self.exps: list[tuple[str, float]] = []      # (resource, end_hour)
        self.batches: dict[str, tuple] = {}          # building -> (out_key,out_qty,end_hour,dest)
        self.craft = None                            # (item_id, tier, end_hour)
        self.last_income_h = 0.0
        self.last_h = 0.0          # для регена HP между заходами
        # бухгалтерия краны/стоки
        self.faucet: dict[str, float] = defaultdict(float)
        self.sink: dict[str, float] = defaultdict(float)

    # — производные параметры таверны (реальные формулы) —
    @property
    def capacity(self):
        return balance.stats_for_level(self.level)["capacity"]

    @property
    def income_rate(self):
        return balance.stats_for_level(self.level)["income_rate"]

    @property
    def slots(self):
        return 1 + self.level // 3   # logic.expedition_slots

    def can_afford(self, cost: dict) -> bool:
        for r, n in cost.items():
            have = self.gold if r == "gold" else self.inventory.get(r, 0)
            if have < n:
                return False
        return True

    def pay(self, cost: dict, sink_key: str):
        for r, n in cost.items():
            if not n:
                continue
            if r == "gold":
                self.gold -= n
                self.sink[sink_key] += n
            else:
                self.inventory[r] = max(0, self.inventory.get(r, 0) - n)

    def add_inv(self, r, n):
        self.inventory[r] = self.inventory.get(r, 0) + n


# forecast-кэш: (сигнатура снаряги, enemy_id) -> (winrate, avg_hp)
_FC: dict = {}


def hunt_forecast(p: SimPlayer, enemy, rng):
    key = (tuple(sorted(p.equipment.items())), enemy.id)
    if key not in _FC:
        stats = dict(items.combat_stats(p.equipment))
        _FC[key] = combat.forecast(stats, enemy, balance.BASE_HP, n=50, rng=rng)
    return _FC[key]


# ════════════════════════════════════════════════════════════════════════
#  Тик-движок (по часам; действия — в часы захода)
# ════════════════════════════════════════════════════════════════════════
def simulate_player(strat: Strategy, days: int, rng: random.Random,
                    snapshots: list[int]):
    p = SimPlayer(region=rng.choice(list(balance.REGIONS)))
    total_h = days * 24
    # часы заходов: равномерно в «бодрствующие» 8..23
    waking = list(range(8, 24))
    step = max(1, len(waking) // strat.sessions_per_day)
    session_hours = set(waking[::step][:strat.sessions_per_day])

    snap = {}   # day -> dict снимок
    for h in range(total_h):
        day = h // 24
        hour = h % 24
        if hour in session_hours:
            _check_in(p, strat, float(h), rng)
        if hour == 23 and day in snapshots:
            snap[day] = _snapshot(p)
    if (days - 1) not in snap:
        snap[days - 1] = _snapshot(p)
    return p, snap


def _snapshot(p: SimPlayer) -> dict:
    gdp = balance.tavern_gdp(p.inventory, p.gold, p.level, p.income_rate, p.reputation)
    gdp += items.gear_value(p.equipment) + balance.invested_value(p.level)
    gdp += production.products_value(_tav(p))
    return {"gold": p.gold, "level": p.level, "rep": p.reputation, "gdp": gdp}


class _Tav:
    """Утка-таверна для реальных logic._retail_demand / products_value."""
    __slots__ = ("capacity", "products", "reputation")


def _tav(p: SimPlayer):
    t = _Tav()
    t.products = p.products
    t.capacity = p.capacity
    t.reputation = p.reputation
    return t


def _check_in(p: SimPlayer, s: Strategy, now_h: float, rng: random.Random):
    # 0) реген HP с прошлого захода (полный за HP_REGEN_FULL_HOURS)
    p.hp = min(balance.BASE_HP,
               p.hp + (now_h - p.last_h) * balance.BASE_HP / balance.HP_REGEN_FULL_HOURS)
    p.last_h = now_h

    # 1) забрать вернувшиеся бригады (реальная добыча по региону/уровню)
    kept = []
    for res, end in p.exps:
        if end <= now_h:
            amt = balance.expedition_yield(res, p.level, p.region)
            amt = int(amt * items.yield_multiplier(p.equipment, res))
            if rng.randint(1, 100) <= balance.lucky_chance(
                    items.combat_stats(p.equipment)["luck"]):
                amt *= balance.LUCKY_MULT
            p.add_inv(res, amt)
        else:
            kept.append((res, end))
    p.exps = kept

    # 2) забрать готовое производство
    done = []
    for b, (out_key, qty, end, dest) in p.batches.items():
        if end <= now_h:
            if dest == "cellar":
                p.products[out_key] = p.products.get(out_key, 0) + qty
            else:
                p.add_inv(out_key, qty)
            done.append(b)
    for b in done:
        del p.batches[b]

    # 3) забрать готовый крафт → надеть
    if p.craft and p.craft[2] <= now_h:
        iid, tier, _ = p.craft
        p.equipment[items.CATALOG[iid].slot] = items.make_entry(iid, tier)
        p.craft = None

    # 4) пассивный доход (капается, потолок INCOME_CAP_HOURS)
    hours = min(now_h - p.last_income_h, balance.INCOME_CAP_HOURS)
    if hours > 0:
        inc = int(p.income_rate * hours * items.income_multiplier(p.equipment))
        p.gold += inc
        p.faucet["пассив-доход"] += inc
        # 5) розница гостям (реальная сегментация premium/commoner)
        _retail(p, s, hours)
        # 5b) сбыт излишка товара оптом (что не выпили гости — чтоб не скисло)
        if s.sell_goods_surplus:
            _sell_goods_surplus(p)
        # 6) порча погреба
        _spoil(p, hours)
        p.last_income_h = now_h

    # 7) запустить производство в простаивающих зданиях
    for (b, recipe) in s.plan:
        if b not in p.buildings or b in p.batches:
            continue
        ins, out_key, qty, h, dest = prod_spec(b, recipe, p.level)
        if s.use_shop:
            _shop_topup(p, ins)
        if p.can_afford(ins):
            p.pay(ins, "_прод-сырьё")  # сырьё не золото-сток (кроме gold-входов нет)
            p.batches[b] = (out_key, qty, now_h + h, dest)

    # 8) отправить бригады: ЦЕЛЕВОЙ выбор сырья по дефициту под ближайшую цель
    #    (апгрейд → стройка → производство), иначе — по фокус-корзине стратегии.
    free = p.slots - len(p.exps)
    fi = 0
    for _ in range(max(0, free)):
        pay = max(1, int(balance.worker_pay(p.level) * items.pay_multiplier(p.equipment)))
        if p.gold < pay:
            break
        res = _pick_resource(p, s, fi)
        fi += 1
        p.gold -= pay
        p.sink["плата-бригадам"] += pay
        hrs = balance.EXPEDITION_HOURS * items.speed_multiplier(p.equipment)
        p.exps.append((res, now_h + hrs))

    # 9) охота (реальный бой), пока есть HP и достойная цель
    if s.hunt:
        _hunt_session(p, s, now_h, rng)

    # 10) сбыт сырья купцу (опт, NPC платит → кран)
    if s.sell_raw:
        _sell_raw(p)

    # 11) апгрейд таверны
    if s.upgrade:
        _try_upgrade(p, s)

    # 12) стройка пристроек (мгновенно списываем, ставим в активные на build_hours)
    _try_build(p, s, now_h)

    # 13) крафт снаряги
    if s.craft_order and p.craft is None:
        _try_craft(p, s, now_h)


def _needed_resources(p: SimPlayer, s: Strategy) -> dict:
    """Сколько сырья нужно под ближайшую цель: апгрейд + следующая стройка +
    одна партия производства. Только добываемое сырьё (не полуфабрикаты)."""
    need: dict[str, int] = defaultdict(int)
    if s.upgrade and p.level < balance.MAX_LEVEL:
        for r, n in balance.upgrade_cost(p.level).items():
            if r != "gold":
                need[r] += n
    for bid in s.build_order:
        if bid in p.buildings:
            continue
        b = buildings.CATALOG[bid]
        if all(req in p.buildings for req in b.requires) and p.reputation >= b.req_reputation:
            for r, n in b.cost.items():
                if r != "gold":
                    need[r] += n
        break
    for (bld, recipe) in s.plan:
        if bld in p.buildings:
            ins, *_ = prod_spec(bld, recipe, p.level)
            for r, n in ins.items():
                if r != "gold":
                    need[r] += n
    return need


def _pick_resource(p: SimPlayer, s: Strategy, fallback_i: int) -> str:
    """Самый дефицитный добываемый ресурс под цель; иначе — фокус-корзина."""
    need = _needed_resources(p, s)
    short = {r: n - p.inventory.get(r, 0) for r, n in need.items()
             if r in balance.EXPEDITION_YIELD and n - p.inventory.get(r, 0) > 0}
    if short:
        return max(short, key=short.get)
    if s.expedition_focus:
        return s.expedition_focus[fallback_i % len(s.expedition_focus)]
    return "wood"


def _retail(p: SimPlayer, s: Strategy, hours: float):
    tav = _tav(p)
    want, _pu, _pl = logic._retail_demand(tav, hours, 1.0, 1.0)
    if not want:
        return
    gold = sum(int(q) * unit_price_sim(k) for k, q in want.items() if k in production.GOODS)
    gold = int(gold * logic.assortment_mult(want))
    for k, q in want.items():
        p.products[k] = max(0, p.products.get(k, 0) - int(q))
    p.gold += gold
    p.faucet["розница-гости"] += gold
    # репутация-молва (накопитель)
    total = sum(int(q) for q in want.values())
    prog = p.rep_progress + total * balance.REP_POINTS_RETAIL
    gain = prog // balance.REP_PROGRESS_PER_POINT
    p.rep_progress = prog - gain * balance.REP_PROGRESS_PER_POINT
    p.reputation += gain


def _spoil(p: SimPlayer, hours: float):
    goods = [k for k in production.GOODS if p.products.get(k, 0) > 0]
    total = sum(p.products[k] for k in goods)
    cap = balance.cellar_capacity(p.capacity)
    if total <= cap:
        return
    excess = total - cap
    spoil_total = int(excess * balance.SPOIL_PCT_PER_DAY * hours / 24)
    for k in sorted(goods, key=lambda x: -p.products[x]):
        sp = min(p.products[k], int(round(spoil_total * p.products[k] / total)))
        p.products[k] = max(0, p.products[k] - sp)


def _sell_goods_surplus(p: SimPlayer):
    """Излишек напитков/еды сверх вместимости — сбыть оптом (NPC, ~0.8×розницы)."""
    cap = balance.cellar_capacity(p.capacity)
    for k in list(p.products):
        if k in production.GOODS and p.products[k] > cap // 2:
            sell = p.products[k] - cap // 2
            gold = int(sell * unit_price_sim(k) * 0.8)
            p.products[k] -= sell
            p.gold += gold
            p.faucet["опт-товар"] += gold


def _sell_raw(p: SimPlayer):
    """Сбыт излишка сырья купцу по справедливой цене (NPC платит → кран)."""
    for r in list(p.inventory):
        if r in balance.RESOURCE_PRICE and r in balance.EXPEDITION_YIELD:
            keep = 80
            if p.inventory[r] > keep:
                sell = p.inventory[r] - keep
                gold = int(sell * balance.RESOURCE_PRICE[r])
                p.inventory[r] -= sell
                p.gold += gold
                p.faucet["сбыт-сырьё"] += gold


def _shop_topup(p: SimPlayer, need: dict):
    """Докупить недостающее сырьё в лавке (premium-цена → сток золота)."""
    for r, q in need.items():
        if r == "gold" or r not in balance.EXPEDITION_YIELD:
            continue
        short = q - p.inventory.get(r, 0)
        if short > 0:
            cost = short * shop.price(r)
            if p.gold >= cost:
                p.gold -= cost
                p.sink["лавка-сырьё"] += cost
                p.add_inv(r, short)


def _hunt_session(p: SimPlayer, s: Strategy, now_h: float, rng: random.Random):
    min_hp = max(1, int(balance.BASE_HP * balance.HUNT_MIN_HP_PCT))
    for _ in range(6):   # не больше нескольких боёв за заход
        if p.hp < min_hp:
            break
        best, best_ev = None, 0.0
        for e in combat.huntable(p.region):       # общие + зверь региона игрока
            wr, _ = hunt_forecast(p, e, rng)
            if wr < s.hunt_min_wr:
                continue
            ev = wr / 100 * (e.gold[0] + e.gold[1]) / 2
            if ev > best_ev:
                best, best_ev = e, ev
        if best is None:
            break
        target = combat.maybe_elite(best.id, rng) or best   # редкая элита (Ф3)
        stats = dict(items.combat_stats(p.equipment))
        f = combat.resolve(stats, target, int(p.hp), rng)
        if f.win:
            loot = combat.roll_loot(target, stats.get("luck", 0), rng)
            p.gold += loot["gold"]
            p.faucet["охота"] += loot["gold"]
            for r, q in loot["res"].items():
                p.add_inv(r, q)
            if loot["rep"]:
                p.reputation += loot["rep"]
            p.hp = max(1, min(f.hp_left, p.hp - balance.HUNT_EXERTION))
        else:
            lost = int(p.gold // balance.HUNT_LOSS_GOLD_DIV)
            p.gold -= lost
            p.sink["охота-потери"] += lost
            p.hp = balance.HP_LOSS_FLOOR
            break
    # реген HP до следующего захода учитывается грубо: восстановим к заходам
    # (полный реген за HP_REGEN_FULL_HOURS) — добавим перед выходом немного
    p.hp = min(balance.BASE_HP, p.hp)


def _try_upgrade(p: SimPlayer, s: Strategy):
    for _ in range(3):
        if p.level >= balance.MAX_LEVEL:
            return
        cost = balance.upgrade_cost(p.level)
        if p.gold - cost.get("gold", 0) < s.upgrade_reserve:
            return
        if s.use_shop:
            _shop_topup(p, {k: v for k, v in cost.items() if k != "gold"})
        if not p.can_afford(cost):
            return
        p.pay(cost, "апгрейд")
        p.level += 1
        rep = balance.reputation_for_upgrade(p.level)
        p.reputation += rep


def _try_build(p: SimPlayer, s: Strategy, now_h: float):
    for bid in s.build_order:
        if bid in p.buildings:
            continue
        b = buildings.CATALOG[bid]
        if any(r not in p.buildings for r in b.requires):
            continue
        if p.reputation < b.req_reputation:
            continue
        if p.can_afford(b.cost):
            p.pay(b.cost, "стройка")
            p.buildings.append(bid)   # в симуляции достраиваем сразу (build_hours мал)
        return  # одна стройка за заход


def _try_craft(p: SimPlayer, s: Strategy, now_h: float):
    for iid in s.craft_order:
        item = items.CATALOG.get(iid)
        if item is None or not item.craftable:
            continue
        cur = items.equipped_tier(p.equipment, iid)
        if cur >= items.TIER_MAX:
            continue
        tier = cur + 1
        cost = items.tier_cost(item, tier)
        if s.use_shop:
            _shop_topup(p, {k: v for k, v in cost.items() if k != "gold"})
        if p.can_afford(cost):
            p.pay(cost, "крафт-снаряга")
            p.craft = (iid, tier, now_h + items.tier_hours(item, tier))
            return


# ════════════════════════════════════════════════════════════════════════
#  Монте-Карло
# ════════════════════════════════════════════════════════════════════════
def monte_carlo(strat: Strategy, n: int, days: int, seed: int):
    snaps_at = sorted({0, 6, 13, min(days - 1, 29), days - 1} & set(range(days)) | {days - 1})
    by_day = defaultdict(lambda: defaultdict(list))   # day -> metric -> [values]
    faucet_tot = defaultdict(float)
    sink_tot = defaultdict(float)
    for i in range(n):
        rng = random.Random(seed * 100000 + i)
        p, snap = simulate_player(strat, days, rng, snaps_at)
        for d, s in snap.items():
            for k, v in s.items():
                by_day[d][k].append(v)
        for k, v in p.faucet.items():
            faucet_tot[k] += v
        for k, v in p.sink.items():
            sink_tot[k] += v
    return snaps_at, by_day, faucet_tot, sink_tot


# ════════════════════════════════════════════════════════════════════════
#  Анализы
# ════════════════════════════════════════════════════════════════════════
def hunt_matrix():
    """Винрейт (%) по зверям × стадии прокачки снаряги. Ловит «обрыв»."""
    stages = {
        "голыми руками": {},
        "топор★ (dmg8)": {"right_hand": "master_axe:1"},
        "топор★+фартук★": {"right_hand": "master_axe:1", "chest": "fartuk:1"},
        "ковш★ полный★": {"weapon": "kovsh:1", "chest": "fartuk:1", "left_hand": "oak_shield:1",
                          "head": "leather_cap:1"},
        "тесак★ компон": {"weapon": "fang_cleaver:1", "chest": "fur_coat:1",
                          "left_hand": "oak_shield:1", "head": "leather_cap:1"},
        "ковш★★★ (мастер)": {"weapon": "kovsh:3", "chest": "fartuk:3", "left_hand": "oak_shield:3",
                             "head": "leather_cap:3"},
        "снаряга дракона": {"weapon": "dragon_fang:3", "chest": "dragon_scale:3",
                            "talisman": "dragon_heart:3"},
    }
    rng = random.Random(42)
    rows = []
    for e in combat.ENEMIES:
        row = [e.name]
        for eq in stages.values():
            stats = dict(items.combat_stats(eq))
            wr, _ = combat.forecast(stats, e, balance.BASE_HP, n=300, rng=rng)
            row.append(wr)
        rows.append(row)
    return list(stages), rows


def stat_probe():
    """Маржинальный вклад каждого стата в средний винрейт по всем зверям.
    Бампаем ОДИН стат у базового кита (ковш★+фартук★). База Фазы 0: сейчас урон/
    броня двигают сильно, крит — слабо, удача — почти никак (только пол-крита)."""
    base_eq = {"weapon": "kovsh:1", "chest": "fartuk:1"}

    def mean_wr(extra: dict) -> float:
        stats = dict(items.combat_stats(base_eq))
        for k, v in extra.items():
            stats[k] = stats.get(k, 0) + v
        rng = random.Random(7)
        wrs = [combat.forecast(stats, e, balance.BASE_HP, n=400, rng=rng)[0]
               for e in combat.ENEMIES]
        return sum(wrs) / len(wrs)

    base = mean_wr({})
    rows = [("базовый кит (ковш★+фартук★)", "—", round(base, 1))]
    for label, extra in (("+8 урон", {"damage": 8}), ("+10 крит", {"crit": 10}),
                         ("+10 броня", {"armor": 10}), ("+10 удача", {"luck": 10})):
        m = mean_wr(extra)
        rows.append((label, f"{m - base:+.1f}", round(m, 1)))
    return rows


def _ucost(r: str, L: int) -> float:
    """Плата бригаде за единицу ресурса (себестоимость добычи) — как в
    scripts/audit_production_margin (нейтральная зона)."""
    base, per = balance.EXPEDITION_YIELD[r]
    y = base + per * balance.YIELD_LEVEL_GROWTH * (L - 1)
    return balance.worker_pay(L) / y


def _gather_cost(r: str, qty: int, L: int) -> float:
    if r in ("malt", "flour"):
        return math.ceil(qty / (8 * L)) * 10 * L * _ucost("grain", L)
    if r == "ingot":
        return math.ceil(qty / (4 * L)) * 6 * L * _ucost("ore", L)
    return qty * _ucost(r, L)


def production_roi(level: int = 3):
    """Две базы прибыли/час: (A) над СЕБЕСТОИМОСТЬЮ ДОБЫЧИ — стоит ли вообще
    производить (как dev-аудит); (B) над РЫНКОМ — производить vs продать сырьё."""
    recipes = [
        ("brewery", "1"), ("brewery", "2"), ("brewery", "3"),
        ("kitchen", "roast"), ("winery", "wine"),
        ("meadery", "mead"), ("meadery", "sbiten"),
        ("bakery", "bread"), ("bakery", "pie"),
        ("smokehouse", "cured"), ("smokehouse", "smoked_fish"),
        ("dairy", "cheese"), ("dairy", "butter"),
    ]
    out = []
    for b, r in recipes:
        ins, out_key, qty, hrs, _ = prod_spec(b, r, level)
        revenue = qty * production.GOODS[out_key].price
        gather = sum(_gather_cost(k, v, level) for k, v in ins.items())
        market = sum(balance.RESOURCE_PRICE.get(k, 0) * v for k, v in ins.items())
        out.append((production.GOODS[out_key].name, b, qty, round(revenue),
                    round((revenue - gather) / hrs, 1),     # A: над добычей
                    round((revenue - market) / hrs, 1),     # B: над рынком
                    hrs))
    out.sort(key=lambda x: -x[4])
    return out


def raid_economics():
    """Винрейт и краник золота рейд-боссов при разной явке и снаряге."""
    # средний урон/удар бойца при разной снаряге и уровне
    def hit_dmg(equip, level):
        stats = items.combat_stats(equip)
        return balance.BASE_DAMAGE + stats["damage"] + level * 2
    profiles = {
        "новичок ур.3, без снаряги": ({}, 3),
        "середняк ур.6, топор★": ({"right_hand": "master_axe:1"}, 6),
        "ветеран ур.10, ковш★★": ({"weapon": "kovsh:2"}, 10),
    }
    HITS_PER_FIGHTER = 80   # реалистичный темп тапов за окно боя (из прод-данных 50-150)
    rows = []
    for key, boss in raid.BOSSES.items():
        for pname, (eq, lvl) in profiles.items():
            raw = hit_dmg(eq, lvl)
            per_hit = raid.mitigate(key, raw)
            dmg_per_fighter = per_hit * HITS_PER_FIGHTER
            # минимальная явка, чтобы добить HP (HP сам растёт с явкой)
            need = None
            for N in range(1, 60):
                hp = raid.hp_for(key, N)
                if N * dmg_per_fighter >= hp:
                    need = N
                    break
            pool = boss.gold_pool
            rows.append((boss.name, pname, per_hit, dmg_per_fighter,
                         need, pool, pool // need if need else 0))
    return rows


def sensitivity(base_strat_key: str, n: int, days: int, seed: int):
    """Чувствительность итогового золота к ключевым ручкам (±%)."""
    knobs = [
        ("income_rate (доход/ч)", "_income", [0.7, 1.0, 1.3]),
        ("worker_pay (плата бригадам)", "_pay", [0.5, 1.0, 1.5, 2.0]),
        ("SHOP_PRICE_MARKUP (наценка лавки)", "shop", [2, 3, 5]),
        ("upgrade gold (цена апгрейда)", "_upg", [0.7, 1.0, 1.5]),
    ]
    res = {}
    strat = STRATEGIES[base_strat_key]
    orig_income = balance.stats_for_level
    orig_pay = balance.worker_pay
    orig_markup = balance.SHOP_PRICE_MARKUP
    orig_upg = balance.upgrade_cost
    for label, kind, mults in knobs:
        line = []
        for m in mults:
            # пропатчить ручку
            if kind == "_income":
                balance.stats_for_level = lambda lv, _o=orig_income, _m=m: {
                    **_o(lv), "income_rate": int(_o(lv)["income_rate"] * _m)}
            elif kind == "_pay":
                balance.worker_pay = lambda lv, _m=m: int(balance.WORKER_PAY_PER_LEVEL * lv * _m)
            elif kind == "shop":
                balance.SHOP_PRICE_MARKUP = m
            elif kind == "_upg":
                def _uc(level, _o=orig_upg, _m=m):
                    c = dict(_o(level))
                    c["gold"] = int(c["gold"] * _m)
                    return c
                balance.upgrade_cost = _uc
            golds = []
            for i in range(n):
                rng = random.Random(seed * 7777 + i)
                _p, snap = simulate_player(strat, days, rng, [days - 1])
                golds.append(snap[days - 1]["gold"])
            line.append((m, round(pct(golds, 50))))
            # вернуть как было
            balance.stats_for_level = orig_income
            balance.worker_pay = orig_pay
            balance.SHOP_PRICE_MARKUP = orig_markup
            balance.upgrade_cost = orig_upg
        res[label] = line
    return res


# ════════════════════════════════════════════════════════════════════════
#  Отчёт
# ════════════════════════════════════════════════════════════════════════
def run(players: int, days: int, seed: int):
    OUT.mkdir(exist_ok=True)
    md = []
    md.append("# Экономика «Недоливска» — Монте-Карло отчёт\n")
    md.append(f"Игроков на стратегию: **{players}**, горизонт: **{days} дн.**, "
              f"seed={seed}. Считано на реальных функциях `bot.game.*`.\n")

    # — прогрессия по стратегиям —
    md.append("\n## 1. Прогрессия по архетипам (медиана; p10–p90)\n")
    print("Прогон стратегий…")
    overview = []
    for strat in STRATEGIES.values():
        _snaps_at, by_day, faucet, sink = monte_carlo(strat, players, days, seed)
        last = days - 1
        g = by_day[last]["gold"]; lv = by_day[last]["level"]
        gd = by_day[last]["gdp"]; rp = by_day[last]["rep"]
        overview.append((strat.name, pct(g, 50), pct(g, 10), pct(g, 90),
                         pct(lv, 50), pct(gd, 50), pct(rp, 50), faucet, sink))
        print(f"  {strat.name:26} день{last}: золото~{int(pct(g,50))}, "
              f"ур~{pct(lv,50):.1f}, ВВП~{int(pct(gd,50))}")
    md.append("\n| Стратегия | Золото (мед) | p10–p90 | Уровень | ВВП | Репутация |")
    md.append("|---|--:|--:|--:|--:|--:|")
    for r in overview:
        md.append(f"| {r[0]} | {int(r[1])} | {int(r[2])}–{int(r[3])} | "
                  f"{r[4]:.1f} | {int(r[5])} | {int(r[6])} |")

    # — краны/стоки (инфляция) —
    md.append("\n## 2. Краны и стоки золота (на игрока за весь период)\n")
    md.append("Кран = золото ВХОДИТ в экономику (NPC платит). Сток = золото "
              "ВЫХОДИТ (платится NPC/исчезает). Чистый приток/день = (краны−стоки)/дни.\n")
    md.append("| Стратегия | Краны (∑) | Стоки (∑) | Чистый/день | Главный кран | Главный сток |")
    md.append("|---|--:|--:|--:|---|---|")
    for r in overview:
        faucet, sink = r[7], r[8]
        fa = sum(faucet.values()) / players
        si = sum(sink.values()) / players
        net = (fa - si) / days
        top_f = max(faucet.items(), key=lambda x: x[1])[0] if faucet else "—"
        top_s = max(sink.items(), key=lambda x: x[1])[0] if sink else "—"
        md.append(f"| {r[0]} | {int(fa)} | {int(si)} | {int(net):+} | {top_f} | {top_s} |")

    # — проба статов (Фаза 0: база перед тем, как крит/удача станут важны) —
    md.append("\n## 2b. Проба статов: маржинальный вклад в средний винрейт\n")
    md.append("Бампаем один стат у базового кита, смотрим Δ среднего винрейта по всем "
              "зверям. Фаза-0 база: крит/удача двигают слабо — Фаза 1 это меняет "
              "(крит→пробой брони, удача→уворот).\n")
    md.append("| Изменение | Δ ср. винрейт | Ср. винрейт |")
    md.append("|---|--:|--:|")
    for r in stat_probe():
        md.append(f"| {r[0]} | {r[1]} | {r[2]}% |")

    # — матрица охоты —
    md.append("\n## 3. Матрица охоты: винрейт (%) по снаряге\n")
    stages, rows = hunt_matrix()
    md.append("| Зверь | " + " | ".join(stages) + " |")
    md.append("|---" * (len(stages) + 1) + "|")
    for row in rows:
        cells = " | ".join(f"{v}%" for v in row[1:])
        md.append(f"| {row[0]} | {cells} |")

    # — ROI производства —
    md.append("\n## 4. ROI производства (уровень 3, прибыль/час)\n")
    md.append("**A** = над себестоимостью добычи (стоит ли производить вообще — "
              "совпадает с dev-аудитом, всё +). **B** = над рыночной ценой сырья "
              "(производить vs ПРОДАТЬ сырьё; − значит сырьё выгоднее продать).\n")
    md.append("| Товар | Здание | Выход | Выручка | A: /ч над добычей | B: /ч над рынком | Часы |")
    md.append("|---|---|--:|--:|--:|--:|--:|")
    for r in production_roi(3):
        md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | **{r[4]}** | {r[5]} | {r[6]} |")

    # — экономика рейдов —
    md.append("\n## 5. Экономика рейд-боссов (краник золота + добиваемость)\n")
    md.append("При ~80 ударах на бойца за окно боя. «Нужно бойцов» — минимум, "
              "чтобы добить (HP босса растёт с явкой).\n")
    md.append("| Босс | Профиль бойца | Урон/удар | Урон/боец | Нужно бойцов | Пул | На бойца |")
    md.append("|---|---|--:|--:|--:|--:|--:|")
    for r in raid_economics():
        need = r[4] if r[4] else "не добить"
        md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {need} | {r[5]} | {r[6]} |")

    # — чувствительность —
    md.append("\n## 6. Чувствительность итогового золота к ручкам (стратегия «гиперактив»)\n")
    print("Чувствительность…")
    sens = sensitivity("optimizer", max(40, players // 3), days, seed)
    for label, line in sens.items():
        md.append(f"\n**{label}:** " +
                  ", ".join(f"×{m}→{g}" if isinstance(m, float) else f"{m}→{g}"
                            for m, g in line))

    report = OUT / "report.md"
    report.write_text("\n".join(md), encoding="utf-8")
    print(f"\nОтчёт: {report}")
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=150)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.quick:
        a.players, a.days = 40, 21
    run(a.players, a.days, a.seed)


if __name__ == "__main__":
    main()
