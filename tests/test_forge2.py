"""Кузница 2.0: формат записи слота, заточка, аффиксы."""

import os
import random

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, items, logic  # noqa: E402


def test_parse_full_backward_compatible():
    assert items.parse_full("kovsh") == ("kovsh", 1, 0, "")
    assert items.parse_full("kovsh:2") == ("kovsh", 2, 0, "")
    assert items.parse_full("kovsh:2:3") == ("kovsh", 2, 3, "")
    assert items.parse_full("kovsh:2:3:zloby") == ("kovsh", 2, 3, "zloby")
    # мусор зажимается, неизвестный аффикс отбрасывается
    assert items.parse_full("kovsh:9:99:xxx") == ("kovsh", items.TIER_MAX, items.PLUS_MAX, "")
    # старый parse_entry не ломается на новом формате
    assert items.parse_entry("kovsh:2:3:zloby") == ("kovsh", 2)


def test_make_entry_roundtrip():
    e = items.make_entry("sablya", 3, 4, "farta")
    assert items.parse_full(e) == ("sablya", 3, 4, "farta")
    assert items.make_entry("sablya", 2) == "sablya:2"   # без хвостов — как раньше


def test_sharpen_boosts_combat_stats():
    itm = next(i for i in items.CATALOG.values() if i.damage > 10)
    base = items.combat_stats({itm.slot: items.make_entry(itm.id, 1)})
    plus5 = items.combat_stats({itm.slot: items.make_entry(itm.id, 1, 5)})
    step = max(1, round(itm.damage * 0.10))
    assert plus5["damage"] == itm.damage + 5 * step      # плоский шаг ×5 (~+50%)
    assert plus5["damage"] > base["damage"]


def test_every_sharpen_level_visible_on_small_stats():
    """Регресс жалобы: «заточил и ничего не произошло» — мелкий стат съедался
    округлением вниз. Теперь каждый уровень даёт минимум +1 к ненулевому стату."""
    itm = next(i for i in items.CATALOG.values()
               if 0 < max(i.damage, i.armor, i.luck, i.vitality, i.crit) <= 10)
    prev = items.combat_stats({itm.slot: items.make_entry(itm.id, 1, 0)})
    for pl in range(1, items.PLUS_MAX + 1):
        cur = items.combat_stats({itm.slot: items.make_entry(itm.id, 1, pl)})
        assert sum(cur.values()) > sum(prev.values())      # СТРОГО растёт каждый уровень
        prev = cur


def test_item_combat_gain_delta():
    itm = next(i for i in items.CATALOG.values() if i.damage > 10)
    e = items.make_entry(itm.id, 1, 0)
    d = items.item_combat_gain(e, 1)
    assert d.get("damage", 0) >= 1                          # дельта уровня не пустая


def test_plus_zero_identical_to_old():
    two = list(items.CATALOG.values())[:2]
    eq = {it.slot: items.make_entry(it.id, 1) for it in two}
    eq2 = {k: v + ":0" for k, v in eq.items()}
    old = items.combat_stats(eq)
    assert any(old.values())                    # не сравниваем нули с нулями
    assert old == items.combat_stats(eq2)


def test_affix_adds_flat_by_tier():
    itm = next(i for i in items.CATALOG.values() if i.damage > 0)
    noaff = items.combat_stats({itm.slot: items.make_entry(itm.id, 3)})
    aff = items.combat_stats({itm.slot: items.make_entry(itm.id, 3, 0, "kreposti")})
    assert aff["armor"] == noaff["armor"] + 3 * 3          # +3×ярус брони
    assert aff["damage"] == noaff["damage"]


def test_display_name():
    itm = next(iter(items.CATALOG.values()))
    e = items.make_entry(itm.id, 2, 3, "zloby")
    assert items.display_name(e) == f"{itm.name} злобы +3"
    assert items.display_name(items.make_entry(itm.id, 2)) == itm.name


def test_roll_affix_rates_and_t1_never():
    r = random.Random(7)
    got = sum(1 for _ in range(2000) if logic.roll_affix(2, r))
    assert 400 < got < 600                                  # ~25% на T2
    assert all(logic.roll_affix(1, random.Random(i)) == "" for i in range(100))


def test_sharpen_tables_consistent():
    assert set(balance.SHARPEN_COST_GOLD) == set(balance.SHARPEN_SUCCESS)
    assert max(balance.SHARPEN_COST_GOLD) == items.PLUS_MAX
    costs = [balance.SHARPEN_COST_GOLD[i] for i in sorted(balance.SHARPEN_COST_GOLD)]
    assert costs == sorted(costs)                           # дороже с каждым уровнем


def test_claim_reforge_preserves_sharpen_and_affix():
    """Регресс (аудит 03.07): перековка НАДЕТОЙ вещи на след. ярус сохраняет
    заточку и аффикс (как апгрейд трофеем в рейде, _drop_apply) — иначе вложенное
    в заточку золото (до 2500×ярус за уровень) сгорало бы при каждом апгрейде."""
    from types import SimpleNamespace as NS
    from datetime import datetime, timedelta, timezone
    itm = next(i for i in items.CATALOG.values() if i.craftable and i.damage > 0)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    # надета T1 +4 «злобы», доковалась T2 → должна стать T2 +4 «злобы»
    p = NS(craft_item=items.make_entry(itm.id, 2), craft_ends_at=past,
           equipment={itm.slot: items.make_entry(itm.id, 1, 4, "zloby")})
    r = logic.claim_craft(p)
    assert r.ok
    _id, t, plus, aff = items.parse_full(p.equipment[itm.slot])
    assert (t, plus, aff) == (2, 4, "zloby")               # ярус вырос, заточка+аффикс переехали
    # свежая вещь в ЧУЖОЙ/пустой слот — заточка с нуля (перезаписи чужого нет здесь)
    p2 = NS(craft_item=items.make_entry(itm.id, 1), craft_ends_at=past, equipment={})
    assert logic.claim_craft(p2).ok
    _id2, t2, plus2, _aff2 = items.parse_full(p2.equipment[itm.slot])
    assert (t2, plus2) == (1, 0)


# ── Первая ковка новичка — за четверть цены ─────────────────────────────
def test_first_craft_discount_quote():
    from types import SimpleNamespace as NS
    from bot.game import newbie
    fresh = NS(story={})
    vet = NS(story={"flags": ["nb_first_craft"]})
    assert newbie.craft_cost_mult(fresh) == newbie.FIRST_CRAFT_MULT == 0.2
    assert newbie.craft_cost_mult(vet) == 1.0
    itm = next(i for i in items.CATALOG.values() if i.craftable)
    full = items.tier_cost(itm, 1)
    cheap = items.craft_cost(fresh, itm, 1)
    for k, v in full.items():
        if v:
            assert 0 < cheap[k] <= max(1, int(v * 0.2) + 1), (k, v, cheap[k])
    assert items.craft_cost(vet, itm, 1) == full     # ветерану — полная цена


def test_first_craft_achievable_first_evening():
    """Цель аудита: первая ковка достижима за вечер — стартовый набор + пара
    бригад закрывают сырьё, золота хватает на цену и плату работникам."""
    from types import SimpleNamespace as NS
    from bot.game import balance, newbie
    fresh = NS(story={})
    start_gold = 100 + newbie.STARTER_CHEST["gold"]
    have = {"wood": 10 + 40, "grain": 10 + 40, "hops": 5 + 20, "ore": 0}
    cheapest = min(
        (items.craft_cost(fresh, i, 1) for i in items.CATALOG.values() if i.craftable),
        key=lambda c: sum(c.values()))
    gold_needed = cheapest.get("gold", 0)
    trips = 0
    for k, v in cheapest.items():
        if k == "gold" or not v:
            continue
        short = max(0, v - have.get(k, 0))
        y = max(1, balance.expedition_yield(k, 1, "green_valleys"))
        trips += -(-short // y)                    # бригад до закрытия дефицита
    pay = trips * balance.worker_pay(1)
    assert gold_needed + pay <= start_gold, (cheapest, gold_needed, trips, pay)
    assert trips <= 5, (cheapest, trips)           # «за вечер», не за неделю
