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
    # ── ТИТУЛЫ: у каждого СВОЙ визуальный стиль (не оттенки золота) ──
    Reward("t_zodchy", "🔨", "Титул «Зодчий»",
           "Первый камень лёг твоей рукой — город запомнил.", 10, "title", "zodchy"),
    Reward("t_mason", "🧱", "Титул «Каменщик Недоливска»",
           "Цех каменщиков жмёт тебе руку: стены помнят твой пот.", 25, "title", "mason"),
    Reward("t_pillar", "🏛", "Титул «Столп Общины»",
           "На таких, как ты, держится весь город. Имя звучит на площади.", 80, "title", "pillar"),
    Reward("t_keeper", "🛡", "Титул «Хранитель Твердыни»",
           "Стены стоят твоим радением — Орда обходит город стороной.", 200, "title", "keeper"),
    Reward("t_spark", "⚡", "Титул «Искра Артели»",
           "Твой запал зажигает всю стройку — имя горит электрическим неоном.", 220, "title", "spark"),
    Reward("t_mirage", "🔮", "Титул «Мираж Недоливска»",
           "Имя мерцает и плывёт, как марево над степью в полдень.", 260, "title", "mirage"),
    Reward("t_frost", "❄", "Титул «Хладный Мастер»",
           "Кладка ровна, как лёд, и так же холодно-безупречна. Имя дышит инеем.", 300, "title", "frostw"),
    Reward("t_ember", "🔥", "Титул «Пламенный Зодчий»",
           "Строишь с огнём в руках — имя тлеет жаром кузнечного горна.", 320, "title", "emberw"),
    Reward("t_void", "🌑", "Титул «Тень Основания»",
           "Ты был у первого камня, когда города ещё не существовало. Имя дышит бездной.", 400, "title", "voidw"),
    Reward("t_legend", "👑", "Титул «Вечный Зодчий»",
           "Высшее имя Артели — переливается всеми огнями, как самоцвет-голограмма.", 500, "title", "legend"),
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
    """Владение игрока: titles[] (купленные звания), facades[] (купленные фасады),
    facade (ВЫБРАННЫЙ к показу), title_shown (ВЫБРАННОЕ звание; None=авто-высший),
    recipes[]. Обр.совместимость: одиночный старый `facade` → список facades."""
    a = (getattr(player, "story", None) or {}).get("artel") or {}
    facades = list(a.get("facades") or [])
    if not facades and a.get("facade"):
        facades = [a["facade"]]
    return {"titles": list(a.get("titles") or []),
            "facades": facades, "facade": a.get("facade"),
            "title_shown": a.get("title_shown"),
            "recipes": list(a.get("recipes") or [])}


def _save(player, a: dict) -> None:
    """Записать состояние Лавки (переприсваивание story — для JSONB)."""
    st = dict(player.story or {})
    st["artel"] = {"titles": a["titles"], "facades": a["facades"],
                   "facade": a.get("facade"), "title_shown": a.get("title_shown"),
                   "recipes": a["recipes"]}
    player.story = st


def owns(player, r: Reward) -> bool:
    a = _artel(player)
    if r.kind == "title":
        return r.payload in a["titles"]
    if r.kind == "facade":
        return r.payload in a["facades"]        # владение = в списке купленных
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
    """Выдать награду. Титул/фасад копятся в списки; новый фасад сразу выбирается
    к показу (можно потом сменить в инвентаре)."""
    a = _artel(player)
    if r.kind == "title":
        if r.payload not in a["titles"]:
            a["titles"].append(r.payload)
    elif r.kind == "facade":
        if r.payload not in a["facades"]:
            a["facades"].append(r.payload)
        a["facade"] = r.payload                 # новый фасад — сразу на вывеску
    elif r.kind == "recipe":
        if r.payload not in a["recipes"]:
            a["recipes"].append(r.payload)
    _save(player, a)


def set_title_shown(player, payload: str) -> bool:
    """Выбрать показываемое звание (payload; '' — авто-высший). False — не владеет."""
    a = _artel(player)
    if payload and payload not in a["titles"]:
        return False
    a["title_shown"] = payload or None
    _save(player, a)
    return True


def set_facade(player, payload: str) -> bool:
    """Выбрать фасад вывески (payload; '' — снять). False — не владеет."""
    a = _artel(player)
    if payload and payload not in a["facades"]:
        return False
    a["facade"] = payload or None
    _save(player, a)
    return True


def prestige_options_dto(player) -> dict:
    """Купленные звания/фасады для выбора в инвентаре: бейдж + флаг `shown`."""
    a = _artel(player)
    shown = top_title(player)
    titles = [{"key": k, **TITLE_BADGE[k], "shown": bool(shown and shown["key"] == k)}
              for k in TITLE_RANK if k in a["titles"]]
    fsel = a.get("facade")
    facades = [{"key": k, **FACADE_BADGE[k], "shown": k == fsel}
               for k in FACADE_RANK if k in a["facades"]]
    return {"titles": titles, "facades": facades, "has": bool(titles or facades)}


# ── Показ престижа: титул у имени + фасад вывески ──────────────────────────
# У ТИТУЛОВ — уникальный `style` (визуальная тема, не оттенки золота):
#   stone/bronze/silver/gold — классика; neon/plasma/frost/ember/void/holo —
#   необычные (неон, плазма, иней, жар, бездна, голограмма). style драйвит вид.
# У ФАСАДОВ — классический `tier` (металлик вывески). Ранг титулов по цене —
# у имени показываем ВЫСШИЙ купленный.
TITLE_RANK = ("zodchy", "mason", "pillar", "keeper",
              "spark", "mirage", "frostw", "emberw", "voidw", "legend")
TITLE_BADGE = {
    "zodchy": {"emoji": "🔨", "short": "Зодчий", "style": "stone"},
    "mason":  {"emoji": "🧱", "short": "Каменщик", "style": "bronze"},
    "pillar": {"emoji": "🏛", "short": "Столп Общины", "style": "silver"},
    "keeper": {"emoji": "🛡", "short": "Хранитель Твердыни", "style": "gold"},
    "spark":  {"emoji": "⚡", "short": "Искра Артели", "style": "neon"},
    "mirage": {"emoji": "🔮", "short": "Мираж", "style": "plasma"},
    "frostw": {"emoji": "❄", "short": "Хладный Мастер", "style": "frost"},
    "emberw": {"emoji": "🔥", "short": "Пламенный Зодчий", "style": "ember"},
    "voidw":  {"emoji": "🌑", "short": "Тень Основания", "style": "void"},
    "legend": {"emoji": "👑", "short": "Вечный Зодчий", "style": "holo"},
}
# Короткая подпись стиля (лента на карточке Лавки) — по-русски и с характером.
STYLE_LABEL = {
    "stone": "камень", "bronze": "медь", "silver": "серебро", "gold": "золото",
    "neon": "неон", "plasma": "плазма", "frost": "иней", "ember": "жар",
    "void": "бездна", "holo": "голограмма",
}
FACADE_RANK = ("carved", "gilded", "crested", "blazing")
FACADE_BADGE = {
    "carved":  {"emoji": "🪵", "short": "Резной фасад", "tier": "bronze"},
    "gilded":  {"emoji": "✨", "short": "Златая вывеска", "tier": "silver"},
    "crested": {"emoji": "💎", "short": "Самоцветный герб", "tier": "gold"},
    "blazing": {"emoji": "🔥", "short": "Пылающий герб", "tier": "legendary"},
}


def reward_tier(r: Reward) -> str:
    """Ярус редкости ФАСАДА (для визуала карточки Лавки). '' — не фасад."""
    if r.kind == "facade":
        return FACADE_BADGE.get(r.payload, {}).get("tier", "")
    return ""


def reward_style(r: Reward) -> str:
    """Визуальный стиль ТИТУЛА (neon/ember/holo/…). '' — не титул."""
    if r.kind == "title":
        return TITLE_BADGE.get(r.payload, {}).get("style", "")
    return ""


def top_title(player) -> dict | None:
    """Показываемое звание у имени: ВЫБРАННОЕ (title_shown) если владеет, иначе
    авто-высший по рангу. {key,emoji,short,style}. None — нет титулов."""
    a = _artel(player)
    owned = set(a["titles"])
    chosen = a.get("title_shown")
    if chosen and chosen in owned and chosen in TITLE_BADGE:
        return {"key": chosen, **TITLE_BADGE[chosen]}
    for key in reversed(TITLE_RANK):            # авто — с самого престижного вниз
        if key in owned:
            return {"key": key, **TITLE_BADGE[key]}
    return None


def facade_badge(player) -> dict | None:
    """ВЫБРАННЫЙ фасад вывески (если куплен): {key,emoji,short,tier}. None — нет/снят."""
    a = _artel(player)
    f = a.get("facade")
    return {"key": f, **FACADE_BADGE[f]} if f and f in a["facades"] and f in FACADE_BADGE else None


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
                    # ключ товара рецепта — фронт рисует РЕАЛЬНУЮ иконку блюда/шмотки
                    # вместо эмодзи (у титулов/фасадов good пустой → остаётся эмодзи)
                    "good": r.payload if r.kind == "recipe" else "",
                    "tier": reward_tier(r), "style": reward_style(r)})
    return out
