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
