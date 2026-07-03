"""Декларативное ядро живого города: контекст, предикаты, эффекты, сторилет.

Сторилеты — чистые данные (см. story_content.py). Движок (story_engine.py)
подбирает и резолвит их. Эффекты/предикаты — маленькие классы, чтобы контент
оставался декларативным и тестируемым.
"""

from dataclasses import dataclass, field
from html import escape

from bot.db.models import Player
from bot.game import balance, economy, inventory, story_state


@dataclass
class Ctx:
    """Контекст резолва: игрок, город и сборщики побочных эффектов."""
    player: Player
    city: object | None = None          # CityState | None
    shielded: bool = False              # новичок — иммун к городскому негативу
    chat_echo: list[str] = field(default_factory=list)   # строки-эхо в чат
    chronicle: list[str] = field(default_factory=list)   # записи в летопись
    scheduled: list[tuple[str, float]] = field(default_factory=list)  # (id, ч)


# ─────────────────────────── ПРЕДИКАТЫ ────────────────────────────────
class HasFlag:
    def __init__(self, flag): self.flag = flag
    def check(self, ctx): return story_state.has_flag(ctx.player, self.flag)


class NotFlag:
    def __init__(self, flag): self.flag = flag
    def check(self, ctx): return not story_state.has_flag(ctx.player, self.flag)


class NpcRel:
    def __init__(self, npc, at_least=None, at_most=None):
        self.npc, self.lo, self.hi = npc, at_least, at_most
    def check(self, ctx):
        v = story_state.npc_rel(ctx.player, self.npc)
        return (self.lo is None or v >= self.lo) and (self.hi is None or v <= self.hi)


class Faction:
    def __init__(self, fac, at_least=None, at_most=None):
        self.fac, self.lo, self.hi = fac, at_least, at_most
    def check(self, ctx):
        v = story_state.faction(ctx.player, self.fac)
        return (self.lo is None or v >= self.lo) and (self.hi is None or v <= self.hi)


class MinLevel:
    def __init__(self, n): self.n = n
    def check(self, ctx): return (ctx.player.level or 1) >= self.n


class MinRep:
    def __init__(self, n): self.n = n
    def check(self, ctx): return (ctx.player.reputation or 0) >= self.n


class HasBuilding:
    def __init__(self, bid): self.bid = bid
    def check(self, ctx):
        return self.bid in (getattr(ctx.player.tavern, "buildings", None) or [])


class HasStock:
    """Есть ли в погребе >= qty товара (для выборов с ценой в товаре — иначе
    Product-цена клампится в 0 и награда достаётся даром)."""
    def __init__(self, key, qty=1): self.key, self.qty = key, qty
    def check(self, ctx):
        prod = getattr(ctx.player.tavern, "products", None) or {}
        return int(prod.get(self.key, 0)) >= self.qty


class CitySituation:
    """Активна ли в городе указанная ситуация (для эмерджентных событий)."""
    def __init__(self, sid): self.sid = sid

    def check(self, ctx):
        from datetime import datetime, timezone
        city = ctx.city
        if city is None:
            return False
        now = datetime.now(timezone.utc)
        for s in (city.situations or []):
            if s.get("id") == self.sid and datetime.fromisoformat(s["until"]) > now:
                return True
        return False


class SeasonIs:
    """Сейчас указанный сезон (для тематических событий)."""
    def __init__(self, season_id): self.sid = season_id

    def check(self, ctx):
        from bot.game import season
        return season.current().id == self.sid


# ─────────────────────────── ЭФФЕКТЫ ──────────────────────────────────
def _income_rate(player: Player) -> int:
    return getattr(player.tavern, "income_rate", 0) or 10


class Gold:
    """Деньги. tier — ставка от дохода; sign=-1 — убыток (с потолком, без минуса)."""
    def __init__(self, tier=None, flat=0, sign=1):
        self.tier, self.flat, self.sign = tier, flat, sign

    def apply(self, ctx):
        ir = _income_rate(ctx.player)
        amount = balance.stake(ir, self.tier) if self.tier else self.flat
        amount *= self.sign
        if amount >= 0:
            ctx.player.gold += amount
            economy.record(ctx.player, "story", amount)
        else:
            loss = min(-amount, balance.loss_cap(ctx.player.gold, ir))
            ctx.player.gold -= loss
            economy.record(ctx.player, "story", -loss)


class Res:
    def __init__(self, resource, amount): self.resource, self.amount = resource, amount
    def apply(self, ctx): inventory.add(ctx.player, self.resource, self.amount)


class Product:
    def __init__(self, key, amount): self.key, self.amount = key, amount
    def apply(self, ctx):
        tav = ctx.player.tavern
        if tav is None:
            return
        prod = dict(tav.products or {})
        prod[self.key] = max(0, prod.get(self.key, 0) + self.amount)
        tav.products = prod


class Rep:
    def __init__(self, delta): self.delta = delta
    def apply(self, ctx):
        ctx.player.reputation = max(0, (ctx.player.reputation or 0) + self.delta)
        if ctx.player.tavern is not None:
            ctx.player.tavern.reputation = max(
                0, (ctx.player.tavern.reputation or 0) + self.delta)


class RelTo:
    def __init__(self, npc, delta): self.npc, self.delta = npc, delta
    def apply(self, ctx): story_state.adjust_npc_rel(ctx.player, self.npc, self.delta)


class FacRep:
    """Личная репутация у фракции. Заодно ambient-перетоком двигает силу
    фракции в городе (личное влияние складывается в общую судьбу)."""
    def __init__(self, fac, delta): self.fac, self.delta = fac, delta

    def apply(self, ctx):
        story_state.adjust_faction(ctx.player, self.fac, self.delta)
        spill = int(round(self.delta * balance.CITY_POWER_FROM_REP))
        if spill and ctx.city is not None:
            fp = dict(ctx.city.faction_power or {})
            fp[self.fac] = max(-100, min(100, fp.get(self.fac, 0) + spill))
            ctx.city.faction_power = fp


class SetFlag:
    def __init__(self, flag): self.flag = flag
    def apply(self, ctx): story_state.add_flag(ctx.player, self.flag)


class ClearFlag:
    def __init__(self, flag): self.flag = flag
    def apply(self, ctx): story_state.clear_flag(ctx.player, self.flag)


class Schedule:
    """Отложить будущее событие (цепочка-история)."""
    def __init__(self, storylet_id, after_hours): self.sid, self.h = storylet_id, after_hours
    def apply(self, ctx): ctx.scheduled.append((self.sid, self.h))


class Echo:
    """Строка-эхо в общий чат (социальная текстура). {name} — имя игрока."""
    def __init__(self, template): self.template = template
    def apply(self, ctx):
        # Имя экранируем: уходит в чат как HTML, а в Telegram-имени бывают & < >.
        name = escape(ctx.player.first_name or "Кабатчик")
        ctx.chat_echo.append(self.template.replace("{name}", name))


class Chron:
    """Запись в летопись города. {name} — имя игрока."""
    def __init__(self, template): self.template = template
    def apply(self, ctx):
        # Имя экранируем: летопись рендерится как HTML (chronicle_screen).
        name = escape(ctx.player.first_name or "Кабатчик")
        ctx.chronicle.append(self.template.replace("{name}", name))


class FactionPower:
    """Сдвиг силы фракции в городе (общие последствия). Двигать может любой."""
    def __init__(self, fac, delta): self.fac, self.delta = fac, delta
    def apply(self, ctx):
        if ctx.city is None:
            return
        fp = dict(ctx.city.faction_power or {})
        fp[self.fac] = max(-100, min(100, fp.get(self.fac, 0) + self.delta))
        ctx.city.faction_power = fp


class Mood:
    """Сдвиг настроения города от поступка (добро +, лихо −). Ambient-эффект."""
    def __init__(self, delta): self.delta = delta
    def apply(self, ctx):
        if ctx.city is None:
            return
        ctx.city.mood = int(max(-100, min(100, (ctx.city.mood or 0) + self.delta)))


# ─────────────────────────── СТОРИЛЕТ ──────────────────────────────────
@dataclass(frozen=True)
class Outcome:
    weight: int
    text: str
    effects: tuple = ()


@dataclass(frozen=True)
class Choice:
    label: str
    outcomes: tuple                      # tuple[Outcome, ...]
    requires: tuple = ()                 # предикаты доступности кнопки


@dataclass(frozen=True)
class Storylet:
    id: str
    npc: str | None
    title: str
    text: str
    choices: tuple                       # tuple[Choice, ...]
    weight: int = 10
    preconditions: tuple = ()            # предикаты появления
    arc: str = ""
    scheduled_only: bool = False         # только по очереди (звено цепочки)
