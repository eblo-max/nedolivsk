"""«Слава заведения»: ранги репутации — границы порогов, монотонность бонуса,
показ=действие гостевого дохода, событие-повышение ровно раз (HWM), устойчивость
к падению репутации. Пороги: 10/50/150/400/1000/2500 (верхние 5 — эндгейм)."""
import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import fame  # noqa: E402


def test_rank_thresholds_exact_boundaries():
    assert fame.rank(0) == 0 and fame.rank(9) == 0
    assert fame.rank(10) == 1 and fame.rank(49) == 1
    assert fame.rank(50) == 2 and fame.rank(149) == 2
    assert fame.rank(150) == 3 and fame.rank(399) == 3
    assert fame.rank(400) == 4 and fame.rank(999) == 4
    assert fame.rank(1000) == 5 and fame.rank(2499) == 5
    assert fame.rank(2500) == 6 and fame.rank(999999) == 6
    assert fame.rank(-5) == 0                       # отрицательная rep клампится


def test_upper_ranks_are_endgame():
    """Верхние 5 рангов — заметно круче первого (каждый ≥ ×2 предыдущего)."""
    thr = [t for t, *_ in fame.FAME_RANKS]
    assert thr == [0, 10, 50, 150, 400, 1000, 2500]
    for i in range(2, len(thr)):
        assert thr[i] >= thr[i - 1] * 2             # эндгейм-шаг, не пологий


def test_income_mult_monotonic_and_capped():
    mults = [fame.income_mult(t) for t, *_ in fame.FAME_RANKS]
    assert mults == sorted(mults)                   # не убывает по рангам
    assert mults[0] == 1.0 and abs(mults[-1] - 1.55) < 1e-9
    assert fame.income_pct(0) == 0 and fame.income_pct(2500) == 55


def test_progress_bounds():
    assert fame.progress(0)[0] == 0                 # на дне ранга — 0%
    pct, left, nxt = fame.progress(30)              # между 10 и 50: (30-10)/(50-10)=50%
    assert pct == 50 and left == 20 and nxt == 50
    assert fame.progress(2500) == (100, 0, 2500)    # вершина — 100%, дальше некуда
    assert fame.next_at(2500) is None and fame.next_at(0) == 10


def test_chat_announce_only_high_ranks():
    """Анонс в общий чат — только с «Прославленной» (низкие ранги = DM+тост, не спам)."""
    assert fame.ANNOUNCE_RANK_FROM == 3
    assert not (1 >= fame.ANNOUNCE_RANK_FROM) and not (2 >= fame.ANNOUNCE_RANK_FROM)
    assert 3 >= fame.ANNOUNCE_RANK_FROM and 6 >= fame.ANNOUNCE_RANK_FROM


def test_reward_and_dto_shape():
    assert fame.reward_gold(0) == 0 and fame.reward_gold(6) == 9000
    d = fame.dto(NS(reputation=160))
    assert d["rank"] == 3 and d["title"] == "Прославленная таверна"
    assert d["income_pct"] == 18 and d["next_at"] == 400 and d["top"] is False
    top = fame.dto(NS(reputation=3000))
    assert top["top"] is True and top["next_at"] is None and top["progress"] == 100


def test_pop_rankups_once_and_cascades():
    t = NS(reputation=0, fame_rank=0)
    assert fame.pop_rankups(t) == []                # ранг 0 — нечего праздновать
    t.reputation = 160                              # сразу перескочил 10, 50 и 150
    assert fame.pop_rankups(t) == [1, 2, 3]         # каскад: три ранга разом
    assert t.fame_rank == 3
    assert fame.pop_rankups(t) == []               # повторно — пусто (HWM)
    t.reputation = 400
    assert fame.pop_rankups(t) == [4] and t.fame_rank == 4


def test_rep_drop_keeps_hwm_no_reaward():
    """Падение репутации (сюжет) не сбрасывает взятый ранг и не выдаёт награду снова;
    титул/бонус при этом следуют ТЕКУЩЕЙ репутации (показ=действие)."""
    t = NS(reputation=450, fame_rank=0)
    assert fame.pop_rankups(t) == [1, 2, 3, 4]      # взял до «Гордости» (≥400)
    t.reputation = 30                               # реп упала ниже
    assert fame.pop_rankups(t) == []               # награду заново НЕ дают
    assert t.fame_rank == 4                          # HWM держится
    assert fame.title(t.reputation) == "Кабак"      # но титул — по текущей репутации
    assert fame.income_pct(t.reputation) == 5
    t.reputation = 500                              # снова выросла в пределах взятого
    assert fame.pop_rankups(t) == []               # не празднуем уже взятое
    t.reputation = 1000                             # перешагнул новый порог (1000)
    assert fame.pop_rankups(t) == [5]


def test_backfill_sql_thresholds_match_ranks():
    """Одноразовый BACKFILL в base.py (тихая инициализация HWM существующим игрокам,
    чтобы не выдать ретро-награды/спам на деплое) должен использовать ТЕ ЖЕ пороги,
    что fame.FAME_RANKS — иначе на старте ранги посчитаются неверно."""
    import pathlib
    import re
    src = pathlib.Path(__file__).resolve().parents[1] / "bot" / "db" / "base.py"
    m = re.search(r"UPDATE taverns SET fame_rank = CASE(.+?)END", src.read_text("utf-8"), re.S)
    assert m, "backfill-UPDATE пропал из base.py"
    sql = [(int(v), int(r)) for v, r in re.findall(r"reputation >= (\d+) THEN (\d+)", m.group(1))]
    want = [(t, i) for i, (t, *_) in enumerate(fame.FAME_RANKS) if i > 0][::-1]  # по убыв., без ранга 0
    assert sql == want, f"backfill-пороги {sql} ≠ FAME_RANKS {want}"


def test_noble_chance_tip_grow_with_rank():
    """🎩 Знатные гости (Ф2): на дне ранга не заходят; шанс и щедрость растут."""
    ch = [fame.noble_chance(i) for i in range(len(fame.FAME_RANKS))]
    tp = [fame.noble_tip(i) for i in range(len(fame.FAME_RANKS))]
    assert ch[0] == 0.0 and tp[0] == 0.0            # ранг 0 — публика небогатая
    assert ch == sorted(ch) and tp == sorted(tp)    # монотонно растут
    assert 0 < ch[-1] <= 0.5 and 0 < tp[-1] <= 0.5  # но в разумных пределах
    assert fame.noble_chance(99) == 0 and fame.noble_tip(-1) == 0  # вне диапазона — 0


def test_noble_tip_gold_gate_and_amount():
    class RNG:
        def __init__(self, v): self.v = v
        def random(self): return self.v
    # ранг 6 (rep 2500): шанс 30%. rng<chance → зашёл, доля 35%; rng>=chance → 0
    assert fame.noble_tip_gold(2500, 1000, RNG(0.0)) == 350
    assert fame.noble_tip_gold(2500, 1000, RNG(0.99)) == 0
    assert fame.noble_tip_gold(2500, 0, RNG(0.0)) == 0     # нет базы — нет чаевых
    assert fame.noble_tip_gold(0, 1000, RNG(0.0)) == 0     # ранг 0 — не заходят
    assert fame.noble_tip_gold(2500, 3, RNG(0.0)) == 1     # чаевые ≥ 1 (не проваливаются в 0)


def test_noble_tip_is_bonus_not_in_base_gold():
    """Показ=действие: чаевые начислены в кошель, но НЕ в возвращаемом base gold
    (иначе показ retail_total разошёлся бы с ним). Гость сверх базы, помечен."""
    import random as _r
    from bot.game import logic
    t = NS(level=5, reputation=2500, products={"ale1": 50}, rep_progress=0)
    p = NS(tavern=t, gold=0, reputation=2500, buff_kind=None, buff_until=None,
           region="green_valleys", bonus_kind=None, story={}, perks={}, econ={})
    base_show = logic.retail_total({"ale1": 20}, p)
    got_noble = False
    for seed in range(60):                          # заведомо поймаем визит (шанс 30%)
        _r.seed(seed)
        t.products = {"ale1": 50}; p.gold = 0
        _sold, gold, _rep, noble = logic.apply_retail(p, t, {"ale1": 20})
        assert gold == base_show                    # база всегда == показу (чаевые вне base)
        if noble:
            got_noble = True
            assert p.gold == gold + noble["tip"]     # кошель = база + чаевые
            assert noble["tip"] >= 1
    assert got_noble, "за 60 сделок знатный гость так и не зашёл — проверь шанс"


def test_badge_public_prestige():
    """Ф1: престиж-бейдж для витрин (рейтинг/карта). None на ранге 0, иначе
    {rank,title} из ТОЙ ЖЕ fame.rank (показ=действие престижа)."""
    assert fame.badge(0) is None and fame.badge(9) is None      # безымянных не светим
    assert fame.badge(10) == {"rank": 1, "title": "Кабак"}
    assert fame.badge(854) == {"rank": 4, "title": "Гордость Недоливска"}
    assert fame.badge(9999) == {"rank": 6, "title": "Живая легенда"}
    for rep in (0, 5, 10, 55, 160, 500, 1200, 3000):            # согласован с rank/title
        b = fame.badge(rep)
        assert (b is None) == (fame.rank(rep) == 0)
        if b:
            assert b["rank"] == fame.rank(rep) and b["title"] == fame.title(rep)


def test_dto_exposes_noble_info():
    d = fame.dto(NS(reputation=2500))
    assert d["noble_chance"] == 30 and d["noble_tip"] == 35
    assert fame.dto(NS(reputation=0))["noble_chance"] == 0


def test_retail_income_applies_fame_buff_show_equals_apply():
    """Гостевой доход реально множится на бонус ранга — та же котировка на показ и
    начисление (logic.retail_total). Без таверны — множитель не падает."""
    from bot.game import logic
    prods = {"ale1": 10}
    t_lo = NS(level=3, reputation=0)
    t_hi = NS(level=3, reputation=2500)             # +55%
    p_lo = NS(tavern=t_lo, buff_kind=None, buff_until=None, region="green_valleys",
              bonus_kind=None, story=None, perks={})
    p_hi = NS(tavern=t_hi, buff_kind=None, buff_until=None, region="green_valleys",
              bonus_kind=None, story=None, perks={})
    lo = logic.retail_total(prods, p_lo)
    hi = logic.retail_total(prods, p_hi)
    assert lo > 0 and hi == int(lo * 1.55)          # ровно заявленные +55%
    p_hi.tavern = None
    assert logic.retail_total(prods, p_hi) == lo    # нет таверны → нет буфа, не падаем
