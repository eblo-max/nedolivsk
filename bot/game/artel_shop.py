"""Лавка Артели зодчих — СТОК валюты «Зодар» (Фаза 2).

Зодар (Player.zodar) — bind-on-earn: не купить/не продать, только за участие в
стройках (см. bot/game/wonder.py). Здесь его ТРАТЯТ на престиж. Каталог —
титулы и фасад (хранятся в player.story['artel'], показ — Фаза 3 UI). Цены
фикс — сток без инфляции. Эксклюзив-рецепты (вживление в производство) — Фаза 2b.

Чистые помощники: каталог, «уже куплено», применение. DB-операции (лок, списание
зодара) — в эндпоинте bot/webapi/artel.py. См. docs/wonders.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Reward:
    id: str
    emoji: str
    name: str
    desc: str
    cost: int             # в зодарах ⚒
    kind: str             # 'title' | 'facade'
    payload: str          # id титула / фасада (хранится в story['artel'])


# Каталог Лавки. Цены 10–80 ⚒ (топ-престиж = несколько чудес → долгий чейз).
CATALOG: list[Reward] = [
    Reward("t_zodchy", "🔨", "Титул «Зодчий»",
           "Звание у имени — ты поднимал чудеса города.", 10, "title", "zodchy"),
    Reward("t_mason", "🧱", "Титул «Каменщик Недоливска»",
           "Уважение цеха каменщиков за вклад в стройки.", 25, "title", "mason"),
    Reward("f_carved", "🪵", "Резной фасад таверны",
           "Артель украсит твою вывеску — видно гостям и на карте.", 40, "facade", "carved"),
    Reward("t_pillar", "🏛", "Титул «Столп общины»",
           "Высшее звание строителя — имя, что помнит весь город.", 80, "title", "pillar"),
]
_BY_ID = {r.id: r for r in CATALOG}


def get(item_id: str) -> Reward | None:
    return _BY_ID.get(item_id)


def _artel(player) -> dict:
    """Состояние Лавки игрока (владение): {titles:[...], facade: id|None}."""
    a = (getattr(player, "story", None) or {}).get("artel") or {}
    return {"titles": list(a.get("titles") or []), "facade": a.get("facade")}


def owns(player, r: Reward) -> bool:
    a = _artel(player)
    if r.kind == "title":
        return r.payload in a["titles"]
    if r.kind == "facade":
        return a["facade"] == r.payload
    return False


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
    st = dict(player.story or {})
    st["artel"] = a
    player.story = st


def catalog_dto(player) -> list[dict]:
    """Каталог для экрана: цена, куплено ли, по карману ли (показ=действие: cost тот
    же, что спишется)."""
    z = int(getattr(player, "zodar", 0) or 0)
    out = []
    for r in CATALOG:
        have = owns(player, r)
        out.append({"id": r.id, "emoji": r.emoji, "name": r.name, "desc": r.desc,
                    "cost": r.cost, "kind": r.kind, "owned": have,
                    "affordable": z >= r.cost})
    return out
