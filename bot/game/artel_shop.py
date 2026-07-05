"""Лавка Артели зодчих — СТОК валюты «Зодар» (Фаза 2 + 2b).

Зодар (Player.zodar) — bind-on-earn: не купить/не продать, только за участие в
стройках (см. bot/game/wonder.py). Здесь его ТРАТЯТ. Каталог: престиж (титулы,
фасад) + эксклюзив-РЕЦЕПТЫ (Ф2b) — дорогие чертежи, что навсегда открывают варку
имба-товаров и ковку имба-шмотки. Всё владение — в player.story['artel']
(titles / facade / recipes). Цены фикс — сток без инфляции.

Гейт варки/ковки по владению рецептом — на стороне production.EXCLUSIVE и
items.WONDER_GEAR (зовут owns_recipe отсюда). DB-операции (лок, списание зодара) —
в эндпоинте bot/webapi/artel.py. См. docs/wonders.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Reward:
    id: str
    emoji: str
    name: str
    desc: str
    cost: int             # в зодарах ⚒
    kind: str             # 'title' | 'facade' | 'recipe'
    payload: str          # титул/фасад ИЛИ ключ рецепта (production-good или item_id шмотки)
    building: str = ""    # для рецептов: где варится/куётся (показ в Лавке)
    effect: str = ""      # для рецептов: короткая строка «что даёт» (показ в Лавке)


# Каталог Лавки. Престиж 10–80 ⚒; эксклюзив-рецепты (Ф2b) 220–450 ⚒ — самый
# долгий чейз (несколько чудес), потому и товар с них — имба (мотив вкладываться).
CATALOG: list[Reward] = [
    # ── Эпик-лестница ТИТУЛОВ (bronze→silver→gold→legendary) ──
    Reward("t_zodchy", "🔨", "Титул «Зодчий»",
           "Первый камень лёг твоей рукой — город запомнил.", 10, "title", "zodchy"),
    Reward("t_mason", "🧱", "Титул «Каменщик Недоливска»",
           "Цех каменщиков жмёт тебе руку: стены помнят твой пот.", 25, "title", "mason"),
    Reward("t_pillar", "🏛", "Титул «Столп Общины»",
           "На таких, как ты, держится весь город. Имя звучит на площади.", 80, "title", "pillar"),
    Reward("t_keeper", "🛡", "Титул «Хранитель Твердыни»",
           "Стены стоят твоим радением — Орда обходит город стороной.", 200, "title", "keeper"),
    Reward("t_legend", "👑", "Титул «Вечный Зодчий»",
           "Высшее имя Артели. Тебя впишут в летопись, что переживёт стены.", 500, "title", "legend"),
    # ── Эпик-лестница ФАСАДОВ вывески ──
    Reward("f_carved", "🪵", "Резной фасад",
           "Артель вырежет узор по вывеске — гости заглядываются.", 40, "facade", "carved"),
    Reward("f_gilded", "✨", "Златая вывеска",
           "Сусальное золото по краю вывески — видно за версту.", 120, "facade", "gilded"),
    Reward("f_crested", "💎", "Самоцветный герб",
           "Герб Артели с самоцветами над дверью — богатеи кивают уважительно.", 300, "facade", "crested"),
    Reward("f_blazing", "🔥", "Пылающий герб Артели",
           "Герб, что тлеет вечным углём Твердыни. Легенда среди вывесок.", 600, "facade", "blazing"),
    # ── Эксклюзив-рецепты (Ф2b): чертёж куплен раз — варишь/куёшь навсегда ──
    Reward("r_feast", "🍗", "Рецепт «Пир зодчих»",
           "Чертёж артельного стола. Варишь на КУХНЕ — снедь, что ставит бойца на ноги.",
           220, "recipe", "zodchy_feast", "Кухня", "+45 ❤ на бой (лучшая еда в игре)"),
    Reward("r_loaf", "🍞", "Рецепт «Каравай каменщика»",
           "Чертёж плотного каравая. Печёшь в ПЕКАРНЕ — держит удар и рушит яд.",
           240, "recipe", "mason_loaf", "Пекарня", "+28% уворота и антидот на бой"),
    Reward("r_nectar", "🍷", "Рецепт «Артельный нектар»",
           "Чертёж крепкого нектара. Гонишь в ВИНОКУРНЕ — рука бьёт без промаха.",
           260, "recipe", "artel_nectar", "Винокурня", "+20% крита на бой"),
    Reward("r_sbiten", "⚡", "Рецепт «Громовой сбитень»",
           "Чертёж грозового сбитня. Варишь в МЕДОВАРНЕ — удар как обвал стены.",
           260, "recipe", "thunder_sbiten", "Медоварня", "+22 урона на бой"),
    Reward("r_hammer", "⚒", "Чертёж «Молот Зодчего»",
           "Чертёж артельного молота. Куёшь в КУЗНИЦЕ — сильнейшее оружие Недоливска, надел и владеешь.",
           450, "recipe", "zodchy_hammer", "Кузница", "Оружие: урон 50, крит 15 (БиС)"),
]
_BY_ID = {r.id: r for r in CATALOG}


def get(item_id: str) -> Reward | None:
    return _BY_ID.get(item_id)


def _artel(player) -> dict:
    """Состояние Лавки игрока (владение): {titles:[...], facade: id|None, recipes:[...]}"""
    a = (getattr(player, "story", None) or {}).get("artel") or {}
    return {"titles": list(a.get("titles") or []), "facade": a.get("facade"),
            "recipes": list(a.get("recipes") or [])}


def owns(player, r: Reward) -> bool:
    a = _artel(player)
    if r.kind == "title":
        return r.payload in a["titles"]
    if r.kind == "facade":
        return a["facade"] == r.payload
    if r.kind == "recipe":
        return r.payload in a["recipes"]
    return False


def owns_recipe(player, key: str) -> bool:
    """Владеет ли игрок рецептом с данным ключом (production-good или item_id шмотки).
    Зовётся из production.EXCLUSIVE и items.WONDER_GEAR как единый гейт варки/ковки."""
    return key in _artel(player)["recipes"]


def owned_recipe_ids(player) -> set[str]:
    """Ключи рецептов, которыми игрок владеет."""
    return set(_artel(player)["recipes"])


def owned_ids(player) -> set[str]:
    """id наград, которыми игрок уже владеет (гейт «уже куплено»)."""
    return {r.id for r in CATALOG if owns(player, r)}


def apply(player, r: Reward) -> None:
    """Выдать награду (мутирует player.story — переприсваивание для JSONB)."""
    a = _artel(player)
    if r.kind == "title":
        if r.payload not in a["titles"]:
            a["titles"].append(r.payload)
    elif r.kind == "facade":
        a["facade"] = r.payload
    elif r.kind == "recipe":
        if r.payload not in a["recipes"]:
            a["recipes"].append(r.payload)
    st = dict(player.story or {})
    st["artel"] = a
    player.story = st


# ── Показ престижа: титул у имени + фасад вывески (эпик-ярусы редкости) ─────
# tier ∈ bronze<silver<gold<legendary — драйвит визуал (цвет/сияние/шиммер).
# Ранг титулов по возрастанию престижа — у имени показываем ВЫСШИЙ купленный.
TITLE_RANK = ("zodchy", "mason", "pillar", "keeper", "legend")
TITLE_BADGE = {
    "zodchy": {"emoji": "🔨", "short": "Зодчий", "tier": "bronze"},
    "mason":  {"emoji": "🧱", "short": "Каменщик", "tier": "bronze"},
    "pillar": {"emoji": "🏛", "short": "Столп Общины", "tier": "silver"},
    "keeper": {"emoji": "🛡", "short": "Хранитель Твердыни", "tier": "gold"},
    "legend": {"emoji": "👑", "short": "Вечный Зодчий", "tier": "legendary"},
}
FACADE_RANK = ("carved", "gilded", "crested", "blazing")
FACADE_BADGE = {
    "carved":  {"emoji": "🪵", "short": "Резной фасад", "tier": "bronze"},
    "gilded":  {"emoji": "✨", "short": "Златая вывеска", "tier": "silver"},
    "crested": {"emoji": "💎", "short": "Самоцветный герб", "tier": "gold"},
    "blazing": {"emoji": "🔥", "short": "Пылающий герб", "tier": "legendary"},
}


def reward_tier(r: Reward) -> str:
    """Ярус редкости награды (для эпик-визуала карточки Лавки). '' — у рецептов."""
    if r.kind == "title":
        return TITLE_BADGE.get(r.payload, {}).get("tier", "")
    if r.kind == "facade":
        return FACADE_BADGE.get(r.payload, {}).get("tier", "")
    return ""


def top_title(player) -> dict | None:
    """Высший купленный титул для показа у имени: {key,emoji,short,tier}. None — нет."""
    owned = set(_artel(player)["titles"])
    for key in reversed(TITLE_RANK):            # с самого престижного вниз
        if key in owned:
            return {"key": key, **TITLE_BADGE[key]}
    return None


def facade_badge(player) -> dict | None:
    """Купленный фасад вывески: {key,emoji,short,tier}. None — нет."""
    f = _artel(player)["facade"]
    return {"key": f, **FACADE_BADGE[f]} if f in FACADE_BADGE else None


def prestige_dto(player) -> dict:
    """Витрина престижа игрока (титул + фасад) — для экрана таверны/рейтинга/карты."""
    return {"title": top_title(player), "facade": facade_badge(player)}


def catalog_dto(player) -> list[dict]:
    """Каталог для экрана: цена, куплено ли, по карману ли (показ=действие: cost тот
    же, что спишется). Для рецептов — где варится и что даёт."""
    z = int(getattr(player, "zodar", 0) or 0)
    out = []
    for r in CATALOG:
        have = owns(player, r)
        out.append({"id": r.id, "emoji": r.emoji, "name": r.name, "desc": r.desc,
                    "cost": r.cost, "kind": r.kind, "owned": have,
                    "affordable": z >= r.cost,
                    "building": r.building, "effect": r.effect,
                    "tier": reward_tier(r)})
    return out
