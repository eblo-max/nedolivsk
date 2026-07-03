"""Исчерпывающий аудит числовых рассинхронов: property-based сверка КАЖДОЙ
пары «показ ↔ действие» в тысячах случайных состояний.

Метод, а не выборка: если показанное число и реальное действие считаются
одной формулой, рассинхрон невозможен by construction; тест это доказывает
на широком диапазоне значений (где живут баги округления/капов/множителей)."""

import os
import random
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance, combat, items, logic  # noqa: E402

SEEDS = range(1500)


def _tavern(r):
    return NS(level=r.randint(1, 8), income_rate=r.randint(5, 300),
              products={}, upgrades=[], buildings=[], reputation=r.randint(0, 200),
              comfort=r.randint(0, 30), capacity=r.randint(10, 60),
              last_income_at=None, rep_progress=0, auction_sold=0, production={})


def _player(r, tav):
    eq = {}
    if r.random() < 0.6:                       # половина — со снарягой
        for it in r.sample(list(items.CATALOG.values()), r.randint(0, 4)):
            eq[it.slot] = items.make_entry(it.id, r.randint(1, 3), r.randint(0, 5))
    return NS(level=tav.level, gold=r.randint(0, 50000), equipment=eq,
              inventory={k: r.randint(0, 500) for k in ("wood", "grain", "hops", "ore")},
              buff_kind=None, buff_until=None, perks={}, region="green_valleys",
              reputation=tav.reputation, story={"faction": {}}, tavern=tav,
              hp=None, hp_at=None, econ={})


# ── 1. ДОХОД: показ /ч == реальному начислению за 1 час ────────────────────
def test_income_show_equals_accrual():
    from datetime import datetime, timedelta, timezone
    bad = 0
    for seed in SEEDS:
        r = random.Random(seed)
        tav = _tavern(r)
        p = _player(r, tav)
        shown = logic.income_rate_quote(p, tav)
        tav.last_income_at = datetime.now(timezone.utc) - timedelta(hours=1)
        res = logic.collect_income(p, tav)
        accrued = int(getattr(res, "passive", 0) or 0)
        if shown != accrued:
            bad += 1
    assert bad == 0, f"доход показ≠начисление в {bad}/{len(SEEDS)} состояниях"


# ── 2. ЗАТОЧКА: показанная дельта == реальному приросту статов ─────────────
def test_sharpen_gain_equals_stat_delta():
    bad = []
    for seed in SEEDS:
        r = random.Random(seed)
        it = r.choice([i for i in items.CATALOG.values()
                       if max(i.damage, i.armor, i.crit, i.luck, i.vitality) > 0])
        tier, plus = r.randint(1, 3), r.randint(0, 4)
        entry = items.make_entry(it.id, tier, plus)
        gain = items.item_combat_gain(entry, plus + 1)          # ПОКАЗ
        before = items.combat_stats({it.slot: entry})
        after = items.combat_stats({it.slot: items.make_entry(it.id, tier, plus + 1)})
        real = {k: after[k] - before[k] for k in after if after[k] != before[k]}
        # показанные ключи должны точно совпасть с реальной дельтой
        for k, v in gain.items():
            if real.get(k, 0) != v:
                bad.append((it.id, tier, plus, k, v, real.get(k, 0)))
    assert not bad, f"заточка показ≠прирост: {bad[:5]}"


# ── 3. ЛЕЧЕНИЕ: показанное +N == реальному приросту HP (с капом) ───────────
def test_heal_show_equals_hp_gain():
    from datetime import datetime, timezone
    bad = []
    for seed in SEEDS:
        r = random.Random(seed)
        tav = _tavern(r)
        p = _player(r, tav)
        key = r.choice(list(balance.HEAL_VALUES))
        tav.products = {key: r.randint(1, 20)}          # еда в погребе (иначе heal=None)
        mx = combat.max_hp(p)
        p.hp = r.randint(1, mx)
        p.hp_at = datetime.now(timezone.utc)
        shown = combat.heal_amount(p, key)                       # ПОКАЗ
        cur0 = combat.current_hp(p)
        hres = combat.heal(p, key)                               # ДЕЙСТВИЕ
        healed = hres["healed"] if hres else 0
        expected = min(shown, mx - cur0)
        if healed != expected:
            bad.append((key, shown, cur0, mx, healed, expected))
    assert not bad, f"лечение показ≠прирост: {bad[:5]}"


# ── 4. ЛАВКА: показанная цена == списанию (единый источник price_for) ──────
def test_shop_price_single_source():
    import inspect
    from bot.webapi import torg
    src = inspect.getsource(torg)
    # и показ (_shop_items), и списание — только price_for, ни одного голого price(
    assert src.count("shop.price(") == 0, "лавка использует голый price() где-то"
    assert "shop.price_for(" in src
    # текст-бот тоже
    from bot.handlers import shop as hshop
    hsrc = inspect.getsource(hshop)
    assert hsrc.count("shop.price(") == 0, "текст-бот: голый price()"


def test_shop_bill_uses_personal_price():
    """bill (гейт «хватит золота» в докупке+апгрейде) == сумме price_for
    (фактическое списание). Регресс (аудит 03.07): bill считал по базовой цене,
    враг лиги обходил гейт и уходил в минус; шло мимо строкового скана выше."""
    from types import SimpleNamespace as NS
    from bot.game import shop
    enemy = NS(story={"faction": {"merchants": -80}})     # враг лиги — дороже базы
    friend = NS(story={"faction": {"merchants": 80}})     # друг — дешевле
    res = shop.sellable()[0]
    assert shop.bill(enemy, {res: 5}) == 5 * shop.price_for(enemy, res)
    assert shop.bill(friend, {res: 5}) == 5 * shop.price_for(friend, res)
    assert shop.price_for(enemy, res) > shop.price_for(friend, res)   # лига реально двигает


# ── 5. БРИГАДЫ: показанная плата == списанию (единый expedition_quote) ─────
def test_expedition_pay_single_source():
    bad = 0
    for seed in SEEDS:
        r = random.Random(seed)
        tav = _tavern(r)
        p = _player(r, tav)
        p.gold = 10 ** 9
        p.expeditions = []
        pay_shown, _hours = logic.expedition_quote(p, tav)
        g0 = p.gold
        res = logic.start_expedition(p, tav, "wood")
        if res.ok and (g0 - p.gold) != pay_shown:
            bad += 1
    assert bad == 0, f"плата бригад показ≠списание в {bad} состояниях"


# ── 6. ДОБЫЧА БРИГАД: показанная == начислению (без фарта) ─────────────────
def test_expedition_gain_single_source(monkeypatch):
    import random as _r
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(_r, "randint", lambda a, b: 100)        # фарт не выпал
    bad = 0
    for seed in range(400):
        r = random.Random(seed)
        tav = _tavern(r)
        p = _player(r, tav)
        p.tavern = tav
        for resource in ("wood", "grain", "hops"):
            shown = logic.expedition_gain_quote(p, tav, resource)
            p.inventory = {}
            p.expeditions = [{"resource": resource,
                              "ends_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                              "notified": True}]
            claimed = dict((res, q) for res, q, _luck in logic.claim_expeditions(p))
            if claimed.get(resource, 0) != shown:
                bad += 1
    assert bad == 0, f"добыча бригад показ≠начисление в {bad} состояниях"


# ── 7. ФРАКЦИИ: котировки монотонны и симметричны по рангу ────────────────
def test_faction_quotes_monotone():
    from bot.game import factions as F
    for rep in range(-100, 101, 5):
        p = NS(story={"faction": {"merchants": rep, "thieves": rep, "watch": rep}})
        rank = F.rank_of(rep)
        # чем выше ранг лиги — тем выше множитель цены; лавка зеркальна торгу
        assert abs(F.merchant_price_mult(p) - (1 + 0.03 * rank)) < 1e-9
        # ночная скупка воров не ниже 1 у друзей, не выше 1 у врагов
        m = F.thief_night_sale_mult(p, 23)
        assert (m >= 1.0) == (rank >= 0)


# ── 8. КОВКА: показ и списание — единый craft_cost, ни одного tier_cost ───
def test_craft_cost_single_source():
    import inspect
    # списание (logic.start_craft) и показ (webapi/character, texts) — craft_cost
    assert "items.craft_cost(" in inspect.getsource(logic)
    from bot.webapi import character as ch
    assert "it.craft_cost(" in inspect.getsource(ch)
    from bot import texts
    assert "craft_cost(" in inspect.getsource(texts.forge_item_screen)


# ── 9. РОЗНИЦА: показанная сумма == начислению (все множители, вкл. воров) ──
def test_retail_show_equals_payout(monkeypatch):
    """retail_total (показ) и apply_retail (начисление) — одинаковый набор
    множителей: ночная скупка воров (рассинхрон 03.07) И городской пир feast_mult
    (рассинхрон 03.07 — показ забывал пир, игроку капало больше кнопки)."""
    from datetime import datetime, timezone
    from bot.game import logic as lg, fgoal
    # ночь МСК (23:30 = 20:30 UTC) — час, где ночная скупка воров активна
    monkeypatch.setattr(lg, "_now", lambda: datetime(2026, 7, 3, 20, 30, tzinfo=timezone.utc))
    for seed in range(300):
        r = random.Random(seed)
        thief_rank = r.choice([-2, 0, 2, 3])
        feast = r.choice([1.0, 1.15, 1.25])            # пир то есть, то нет
        monkeypatch.setattr(fgoal, "feast_mult", lambda f=feast: f)
        tav = NS(products={"ale1": 50, "mead": 50}, level=5, reputation=50,
                 rep_progress=0, auction_sold=0, income_rate=40)
        p = NS(level=5, gold=0, equipment={}, inventory={}, buff_kind=None,
               buff_until=None, perks={}, tavern=tav, econ={}, reputation=50,
               story={"faction": {"thieves": thief_rank * 40}})
        want = {"ale1": r.randint(1, 20)}
        shown = lg.retail_total(want, p)
        _sold, gold, _rep = lg.apply_retail(p, tav, dict(want))
        # показ == реально начисленному золоту (оба с ночным бонусом воров И пиром)
        assert shown == gold, (thief_rank, feast, shown, gold)


# ── 10. ДОХОД: текст-бот и мини-апп показывают ОДНО (единая котировка) ─────
def test_bot_and_app_income_show_same():
    """Текст-бот (texts) не показывает сырой tavern.income_rate как «Доход/ч» —
    только income_rate_quote (иначе чат и приложение разойдутся, жалоба 03.07)."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent.joinpath("bot", "texts.py").read_text(encoding="utf-8")
    # показ дохода «💰 Доход — {...}» обязан идти через income_rate_quote
    for m in re.finditer(r"💰 Доход[^\n]*\{([^}]*income[^}]*)\}", src):
        expr = m.group(1)
        assert "income_rate_quote" in expr, f"сырой доход в тексте: {expr[:60]}"
