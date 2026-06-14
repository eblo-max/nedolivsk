"""Симуляция фракций города и эмерджентные городские ситуации (фаза 3).

Сила фракций (CityState.faction_power) копится от решений игроков (эффект
FactionPower в событиях) и медленно дрейфует к нулю. Когда фракция набирает
силу — в городе включается ситуация, бьющая по ВСЕМ участникам чата (с щитом
новичка для негатива). Планировщик — в тике нотифаера. Для экранов держим
лёгкий кэш активной ситуации по чату (как у ярмарки), чтобы не дёргать БД.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, perks, story_state


@dataclass(frozen=True)
class Situation:
    id: str
    faction: str
    emoji: str
    label: str
    demand_mult: float       # множитель спроса (сбыт) для всех
    skim_pct: float          # доля выручки, утекающая (воры/корона)
    negative: bool           # негатив — гасится щитом новичка
    activate_text: str       # анонс в чат при начале
    expire_text: str         # анонс в чат при окончании
    chron: str               # запись в летопись
    mood: int = 0            # к чему тянет настроение города, пока активна


# Одна доминирующая фракция = одна ситуация. Тон — по тон-байблу.
SITUATIONS: dict[str, Situation] = {
    "thieves": Situation(
        id="thieves_rampant", faction="thieves", emoji="🥷",
        label="Воровской беспредел",
        demand_mult=1.0, skim_pct=0.15, negative=True,
        activate_text=(
            "🥷 <b>ВОРОВСКОЙ БЕСПРЕДЕЛ!</b>\n\n"
            "Гильдия обнаглела вконец — шарят по карманам, чистят кассы. "
            "С каждой выручки теперь капает «налог» ворью. Состоишь в "
            "гильдии — тебя не трогают. Остальные — берегите кошели."
        ),
        expire_text="🥷 Воровская вакханалия поутихла — стража поддавила гильдию. Касса снова твоя.",
        chron="Воровская гильдия устроила в Недоливске беспредел.",
        mood=-30,
    ),
    "watch": Situation(
        id="curfew", faction="watch", emoji="👮",
        label="Комендантский час",
        demand_mult=0.85, skim_pct=0.0, negative=True,
        activate_text=(
            "👮 <b>КОМЕНДАНТСКИЙ ЧАС!</b>\n\n"
            "Стража лютует, патрули на каждом углу. Воровать боятся, но и "
            "гуляк поубавилось — гости расходятся по домам затемно. Выручка "
            "просядет, пока капитан не уймётся."
        ),
        expire_text="👮 Комендантский час сняли — народ снова потянулся в кабаки. Гуляем!",
        chron="Стража ввела в Недоливске комендантский час.",
        mood=-20,
    ),
    "merchants": Situation(
        id="merchant_boom", faction="merchants", emoji="💰",
        label="Купеческий бум",
        demand_mult=1.3, skim_pct=0.0, negative=False,
        activate_text=(
            "💰 <b>КУПЕЧЕСКИЙ БУМ!</b>\n\n"
            "Купеческая лига нагнала в город торговцев и денег. Народ при "
            "монете и гуляет от души — спрос подскочил у всех кабаков. "
            "Лови момент, наливай!"
        ),
        expire_text="💰 Купеческий бум схлынул — торговцы разъехались, спрос вернулся к обычному.",
        chron="Купеческая лига устроила в Недоливске торговый бум.",
        mood=40,
    ),
    "crown": Situation(
        id="crown_taxes", faction="crown", emoji="👑",
        label="Королевские поборы",
        demand_mult=1.0, skim_pct=0.10, negative=True,
        activate_text=(
            "👑 <b>КОРОЛЕВСКИЕ ПОБОРЫ!</b>\n\n"
            "Корона затянула пояса — на всех. Сборщики податей шныряют по "
            "кабакам и снимают долю с каждой выручки. Терпим, пока казне не "
            "полегчает."
        ),
        expire_text="👑 Сборщики податей убрались восвояси — выручка снова целиком твоя.",
        chron="Корона обложила Недоливск поборами.",
        mood=-15,
    ),
    "church": Situation(
        id="temperance", faction="church", emoji="⛪",
        label="Великий пост",
        demand_mult=0.75, skim_pct=0.0, negative=True,
        activate_text=(
            "⛪ <b>ВЕЛИКИЙ ПОСТ!</b>\n\n"
            "Церковь вошла в силу и призвала к трезвению. Прихожане каются и "
            "пьют меньше — спрос в кабаках упал. Грешники ждут, пока попустит."
        ),
        expire_text="⛪ Пост окончен — паства возвращается к кружке с утроенной жаждой!",
        chron="Церковь объявила в Недоливске Великий пост.",
        mood=-15,
    ),
}


@dataclass
class CityEffects:
    demand_mult: float = 1.0
    skim_pct: float = 0.0
    label: str = ""
    negative: bool = False


_NEUTRAL = CityEffects()

# Лёгкий кэш активной ситуации по чату (для экранов, без БД).
_cache: dict[int, str] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_situation(city, now: datetime) -> Situation | None:
    for s in (city.situations or []):
        until = datetime.fromisoformat(s["until"])
        if until > now:
            return SITUATIONS.get(s["id"]) or SITUATIONS.get(s.get("faction", ""))
    return None


def current(city, now: datetime | None = None) -> Situation | None:
    """Активная городская ситуация (для экрана города)."""
    if city is None:
        return None
    return _active_situation(city, now or _now())


def effects(city, player, now: datetime | None = None) -> CityEffects:
    """Экономический эффект текущей ситуации на игрока (с учётом щита/перков)."""
    if city is None:
        return _NEUTRAL
    now = now or _now()
    sit = _active_situation(city, now)
    if sit is None:
        return _NEUTRAL
    if sit.negative and story_state.is_shielded(player, now):
        return _NEUTRAL  # новичков негатив города не трогает
    skim = sit.skim_pct
    demand = sit.demand_mult
    # Перки за стояние у фракций гасят профильный негатив ситуации.
    if sit.id == "thieves_rampant" and perks.thieves_skim_immune(player):
        skim = 0.0
    elif sit.id == "crown_taxes" and perks.crown_tax_immune(player):
        skim = 0.0
    elif sit.id == "temperance" and perks.temperance_immune(player):
        demand = 1.0
    elif sit.id == "curfew" and perks.curfew_immune(player):
        demand = 1.0
    return CityEffects(
        demand_mult=demand, skim_pct=skim,
        label=f"{sit.emoji} {sit.label}", negative=sit.negative,
    )


def advance(city, now: datetime | None = None) -> list[tuple[str, Situation]]:
    """Двигает симуляцию города: дрейф силы фракций, старт/конец ситуаций.
    Возвращает события для анонса: [('activate'|'expire', Situation)].
    Мутирует city; кэш обновляется снаружи (refresh_cache)."""
    now = now or _now()
    events: list[tuple[str, Situation]] = []
    drift_h = 0.0  # сколько часов «прошло» этим тиком (для дрейфа настроения)

    # 1) Дрейф силы фракций к нулю (накапливаем дробное через updated_at).
    updated = city.updated_at
    if updated is not None:
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        steps = int(balance.FACTION_DECAY_PER_HOUR
                    * (now - updated).total_seconds() / 3600)
        if steps > 0:
            drift_h = steps / balance.FACTION_DECAY_PER_HOUR
            fp = dict(city.faction_power or {})
            changed = False
            for f, v in list(fp.items()):
                if v > 0:
                    nv = max(0, v - steps)
                elif v < 0:
                    nv = min(0, v + steps)
                else:
                    nv = 0
                if nv != v:
                    fp[f] = nv
                    changed = True
            if changed:
                city.faction_power = fp
            city.updated_at = updated + timedelta(
                hours=steps / balance.FACTION_DECAY_PER_HOUR)
    else:
        city.updated_at = now

    # 2) Истечение активной ситуации.
    active = None
    for s in (city.situations or []):
        if datetime.fromisoformat(s["until"]) > now:
            active = s
            break
    if (city.situations or []) and active is None:
        # была ситуация, срок вышел (SITUATIONS ключуется по фракции)
        ended = SITUATIONS.get((city.situations[0]).get("faction", ""))
        city.situations = []
        city.last_situation_end = now
        if ended is not None:
            events.append(("expire", ended))

    # 3) Старт новой ситуации, если доминирует фракция и прошёл кулдаун.
    if not city.situations:
        cooled = True
        if city.last_situation_end is not None:
            end = city.last_situation_end
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            cooled = (now - end) >= timedelta(
                hours=balance.SITUATION_COOLDOWN_HOURS)
        if cooled:
            fp = city.faction_power or {}
            if fp:
                fac, power = max(fp.items(), key=lambda kv: kv[1])
                if power >= balance.SITUATION_THRESHOLD and fac in SITUATIONS:
                    sit = SITUATIONS[fac]
                    until = now + timedelta(hours=balance.SITUATION_DURATION_HOURS)
                    city.situations = [
                        {"id": sit.id, "faction": fac, "until": until.isoformat()}
                    ]
                    events.append(("activate", sit))

    # 4) Дрейф настроения к цели текущей ситуации (или к 0, если тихо).
    if drift_h > 0:
        sit = _active_situation(city, now)
        target = sit.mood if sit is not None else 0
        mood = city.mood or 0
        move = balance.MOOD_DRIFT_PER_HOUR * drift_h
        if mood < target:
            mood = min(target, mood + move)
        elif mood > target:
            mood = max(target, mood - move)
        city.mood = int(round(mood))
    return events


# ── Кэш активной ситуации (для экранов) ────────────────────────────────
def refresh_cache(city, now: datetime | None = None) -> None:
    sit = _active_situation(city, now or _now())
    if sit is None:
        _cache.pop(city.chat_id, None)
    else:
        _cache[city.chat_id] = f"{sit.emoji} {sit.label}"


def cached_label(chat_id: int | None) -> str | None:
    return _cache.get(chat_id) if chat_id is not None else None


# ── Настроение города (фаза 4b) ────────────────────────────────────────
def mood_value(city) -> int:
    return int(max(-100, min(100, (city.mood or 0)))) if city is not None else 0


def mood_factor(city) -> float:
    """Мягкий ambient-множитель спроса от настроения (±10% на краях)."""
    if city is None:
        return 1.0
    return 1.0 + mood_value(city) / balance.MOOD_DEMAND_DIV
