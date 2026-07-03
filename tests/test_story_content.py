"""Валидатор сид-контента живого города: структура и ссылочная целостность
всех сторилетов. Ловит опечатки в id фракций/ситуаций/сезонов/товаров/NPC,
битые Schedule-цепочки, пустые выборы — на CI, а не в проде."""
import os

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, city as citymod, factions  # noqa: E402
from bot.game import npc as npcmod, production as prod  # noqa: E402
from bot.game.story_content import STORYLETS, _LIST  # noqa: E402

FACS = set(factions.NAMES)
SITS = {s.id for s in citymod.SITUATIONS.values()}
SEASONS = {"spring", "summer", "autumn", "winter"}
TIERS = set(balance.STAKE_MULT)
GOODS = set(prod.GOODS)
NPCS = set(npcmod.CATALOG)


def _effects(sl):
    for ch in sl.choices:
        for oc in ch.outcomes:
            yield from oc.effects


def _preconds(sl):
    yield from sl.preconditions
    for ch in sl.choices:
        yield from (ch.requires or ())


def test_no_duplicate_ids():
    # dict молча перетирает дубли — сверяем с длиной списка
    assert len(_LIST) == len(STORYLETS), "дублирующийся storylet id перетирает контент"


def test_npc_ids_valid():
    bad = [sl.id for sl in STORYLETS.values() if sl.npc is not None and sl.npc not in NPCS]
    assert not bad, f"неизвестный npc в сторилетах: {bad}"


def test_choices_and_outcomes_nonempty():
    for sl in STORYLETS.values():
        assert sl.choices, f"{sl.id}: нет выборов"
        for ch in sl.choices:
            assert ch.outcomes, f"{sl.id}/{ch.label}: нет исходов"
            assert all(oc.weight >= 1 for oc in ch.outcomes), f"{sl.id}: вес исхода < 1"


def test_faction_ids_valid():
    for sl in STORYLETS.values():
        for e in _effects(sl):
            if e.__class__.__name__ in ("FacRep", "FactionPower"):
                assert e.fac in FACS, f"{sl.id}: неизвестная фракция {e.fac!r}"


def test_gold_tiers_and_products_valid():
    for sl in STORYLETS.values():
        for e in _effects(sl):
            cn = e.__class__.__name__
            if cn == "Gold" and getattr(e, "tier", None):
                assert e.tier in TIERS, f"{sl.id}: неизвестный gold tier {e.tier!r}"
            if cn == "Product":
                assert e.key in GOODS, f"{sl.id}: неизвестный товар {e.key!r}"


def test_schedule_targets_exist():
    for sl in STORYLETS.values():
        for e in _effects(sl):
            if e.__class__.__name__ == "Schedule":
                assert e.sid in STORYLETS, f"{sl.id}: Schedule → несуществующий {e.sid!r}"


def test_precondition_ids_valid():
    for sl in STORYLETS.values():
        for p in _preconds(sl):
            cn = p.__class__.__name__
            if cn == "CitySituation":
                assert p.sid in SITS, f"{sl.id}: неизвестная ситуация {p.sid!r}"
            elif cn == "SeasonIs":
                assert p.sid in SEASONS, f"{sl.id}: неизвестный сезон {p.sid!r}"
            elif cn == "NpcRel":
                assert p.npc in NPCS, f"{sl.id}: NpcRel неизвестный npc {p.npc!r}"


# ── Целостность переплетений (флаги-перекличи и цепочки) ────────────────
def test_read_flags_are_set_somewhere():
    """Флаг, что читается (HasFlag/NotFlag), но нигде не ставится → мёртвая
    ветка: сторилет-переклич никогда не всплывёт."""
    set_flags, read_flags = set(), {}
    for sl in STORYLETS.values():
        for e in _effects(sl):
            if e.__class__.__name__ == "SetFlag":
                set_flags.add(e.flag)
        for p in _preconds(sl):
            if p.__class__.__name__ in ("HasFlag", "NotFlag"):
                read_flags.setdefault(p.flag, []).append(sl.id)
    dead = {f: ids for f, ids in read_flags.items() if f not in set_flags}
    assert not dead, f"флаги читаются, но нигде не ставятся: {dead}"


def test_no_orphan_scheduled_only():
    """scheduled_only без входящего Schedule недостижим (мёртвое звено цепочки)."""
    targets = set()
    for sl in STORYLETS.values():
        for e in _effects(sl):
            if e.__class__.__name__ == "Schedule":
                targets.add(e.sid)
    orphans = [sl.id for sl in STORYLETS.values()
               if sl.scheduled_only and sl.id not in targets]
    assert not orphans, f"scheduled_only без входящего Schedule (недостижимы): {orphans}"


def test_schedule_targets_are_scheduled_only():
    """Schedule должен целить в scheduled_only — иначе звено спавнится и само."""
    bad = []
    for sl in STORYLETS.values():
        for e in _effects(sl):
            if e.__class__.__name__ == "Schedule":
                tgt = STORYLETS.get(e.sid)
                if tgt is not None and not tgt.scheduled_only:
                    bad.append((sl.id, e.sid))
    assert not bad, f"Schedule целит в НЕ-scheduled_only: {bad}"


_TIER = {"petty": 1, "minor": 2, "serious": 3, "major": 4}


def test_pricey_costs_gated_on_stock():
    """Выбор с ценой в товаре И КРУПНОЙ наградой (Gold>=serious или FacRep>=10)
    обязан требовать HasStock: иначе Product/Res клампится в 0 и крупная
    награда достаётся даром (эксплойт «продай то, чего нет»)."""
    bad = []
    for s in STORYLETS.values():
        for ch in s.choices:
            stock = {p.key for p in (ch.requires or ())
                     if p.__class__.__name__ == "HasStock"}
            for o in ch.outcomes:
                costs = {e.key for e in o.effects
                         if e.__class__.__name__ == "Product"
                         and getattr(e, "amount", 0) < 0}
                if not costs:
                    continue
                big = any(
                    (e.__class__.__name__ == "Gold" and getattr(e, "sign", 1) > 0
                     and _TIER.get(getattr(e, "tier", None), 0) >= 3)
                    or (e.__class__.__name__ in ("FacRep", "FactionPower")
                        and getattr(e, "delta", 0) >= 10)
                    for e in o.effects)
                if big and not (costs & stock):
                    bad.append(f"{s.id}/{ch.label}")
    assert not bad, ("крупная награда с ценой в товаре без HasStock (даровой "
                     "эксплойт): " + "; ".join(bad))
