"""Память игрока в живом городе: флаги-факты, отношения с NPC, репутация
фракций, текущее событие (pending) и очередь отложенных (queue).

Всё лежит в JSONB-блоке player.story. Меняем только переприсваиванием нового
dict (иначе SQLAlchemy не заметит). Хелперы делают это сами.
"""

import random
from datetime import datetime, timedelta, timezone

from bot.db.models import Player
from bot.game import balance


def _st(player: Player) -> dict:
    return dict(player.story or {})


def _save(player: Player, st: dict) -> None:
    player.story = st


# ── Флаги-факты (вечные) ───────────────────────────────────────────────
def has_flag(player: Player, flag: str) -> bool:
    return flag in (player.story or {}).get("flags", [])


def add_flag(player: Player, flag: str) -> None:
    st = _st(player)
    flags = set(st.get("flags", []))
    flags.add(flag)
    st["flags"] = sorted(flags)
    _save(player, st)


def clear_flag(player: Player, flag: str) -> None:
    st = _st(player)
    flags = [f for f in st.get("flags", []) if f != flag]
    st["flags"] = flags
    _save(player, st)


# ── Отношения с NPC ────────────────────────────────────────────────────
def npc_rel(player: Player, npc_id: str) -> int:
    return int((player.story or {}).get("npc_rel", {}).get(npc_id, 0))


def adjust_npc_rel(player: Player, npc_id: str, delta: int) -> None:
    st = _st(player)
    rel = dict(st.get("npc_rel", {}))
    rel[npc_id] = max(balance.NPC_REL_MIN,
                      min(balance.NPC_REL_MAX, rel.get(npc_id, 0) + delta))
    st["npc_rel"] = rel
    _save(player, st)


# ── Репутация фракций ──────────────────────────────────────────────────
def faction(player: Player, fac_id: str) -> int:
    return int((player.story or {}).get("faction", {}).get(fac_id, 0))


def adjust_faction(player: Player, fac_id: str, delta: int) -> None:
    st = _st(player)
    fac = dict(st.get("faction", {}))
    fac[fac_id] = max(balance.FACTION_MIN,
                      min(balance.FACTION_MAX, fac.get(fac_id, 0) + delta))
    st["faction"] = fac
    _save(player, st)


# ── Текущее событие на решении ─────────────────────────────────────────
def get_trade(player: Player) -> dict | None:
    return (player.story or {}).get("trade")


def set_trade(player: Player, offer: dict | None) -> None:
    st = _st(player)
    if offer is None:
        st.pop("trade", None)
    else:
        st["trade"] = offer
    _save(player, st)


def get_pending(player: Player) -> dict | None:
    return (player.story or {}).get("pending")


def set_pending(player: Player, storylet_id: str, npc_id: str | None) -> None:
    st = _st(player)
    st["pending"] = {
        "id": storylet_id,
        "npc": npc_id,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _save(player, st)


def clear_pending(player: Player) -> None:
    st = _st(player)
    st.pop("pending", None)
    _save(player, st)


# ── Очередь отложенных событий (цепочки) ───────────────────────────────
def queue_push(player: Player, storylet_id: str, after_hours: float) -> None:
    st = _st(player)
    q = list(st.get("queue", []))
    due = datetime.now(timezone.utc) + timedelta(hours=after_hours)
    q.append({"id": storylet_id, "due": due.isoformat()})
    st["queue"] = q
    _save(player, st)


def queue_pop_due(player: Player, now: datetime) -> list[str]:
    """Снять и вернуть id созревших отложенных событий."""
    st = _st(player)
    q = list(st.get("queue", []))
    due, kept = [], []
    for item in q:
        if datetime.fromisoformat(item["due"]) <= now:
            due.append(item["id"])
        else:
            kept.append(item)
    if due:
        st["queue"] = kept
        _save(player, st)
    return due


# ── Кулдаун и щит новичка ──────────────────────────────────────────────
def _random_cooldown_hours() -> float:
    """Случайный кулдаун: иногда всплеск (густо), иначе обычный/затишье."""
    if random.random() < balance.EVENT_BURST_CHANCE:
        return random.uniform(
            balance.EVENT_COOLDOWN_MIN_HOURS, balance.EVENT_BURST_MAX_HOURS)
    return random.uniform(
        balance.EVENT_BURST_MAX_HOURS, balance.EVENT_COOLDOWN_MAX_HOURS)


def set_last_event(player: Player, now: datetime) -> None:
    """Событие отыграло — назначаем СЛУЧАЙНЫЙ срок следующего (то густо, то пусто)."""
    st = _st(player)
    nxt = now + timedelta(hours=_random_cooldown_hours())
    st["next_event_at"] = nxt.isoformat()
    st.pop("last_event_at", None)  # старый ключ больше не нужен
    _save(player, st)


def can_spawn(player: Player, now: datetime) -> bool:
    """Можно ли подкинуть новое личное событие (случайный кулдаун + нет активного)."""
    if get_pending(player):
        return False
    nxt = (player.story or {}).get("next_event_at")
    if nxt and datetime.fromisoformat(nxt) > now:
        return False
    return True


def is_shielded(player: Player, now: datetime) -> bool:
    """Новичок — иммун к городскому негативу: < L3 или первые 48 ч."""
    if (player.level or 1) < balance.NEWBIE_SHIELD_LEVEL:
        return True
    created = player.created_at
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if now - created < timedelta(hours=balance.NEWBIE_SHIELD_HOURS):
            return True
    return False
