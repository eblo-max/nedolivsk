"""«Слава заведения» — ранги репутации таверны. Растущая репутация превращается
в лестницу известности: пассивный бонус гостевого дохода + престиж-титул +
разовая награда с событием на повышении. Концепция — docs/fame.md.

Чистые функции (ранг/титул/множитель/прогресс/награда) — тестируемы без БД;
показ=действие: множитель дохода из ЕДИНОЙ котировки (logic.retail_total),
детект повышения — под локом в _api_state (webapi/tavern.py), ровно раз (HWM
tavern.fame_rank). Пороги откалиброваны под прод (10.07.2026: медиана rep 0,
p90 88, max 854) — первый ранг за пару дней, «Живая легенда» — редкая вершина.
"""

# (порог репутации, титул, множитель гостевого дохода, разовая награда золотом)
# Кривая: 1-й ранг быстрый (зацепка за пару дней), верхние 5 — эндгейм (×2.5 шаг).
# Калибровка под прод (10.07.2026): медиана rep 0, p90 88, MAX 854 → топ-игрок
# садится на 4-й из 6 (Гордость), «Легенда тракта»/«Живая легенда» выше потолка —
# долгие цели на месяцы+. Само не устаревает: растёт мир — растут и вершины.
FAME_RANKS: tuple[tuple[int, str, float, int], ...] = (
    (0,    "Безвестная дыра",        1.00, 0),
    (10,   "Кабак",                  1.05, 100),
    (50,   "Знатный кабак",          1.10, 300),
    (150,  "Прославленная таверна",  1.18, 700),
    (400,  "Гордость Недоливска",    1.28, 1600),
    (1000, "Легенда тракта",         1.40, 4000),
    (2500, "Живая легенда",          1.55, 9000),
)
MAX_RANK = len(FAME_RANKS) - 1
# С какого ранга повышение достойно анонса в ОБЩИЙ чат (ниже — только личный DM +
# тост, иначе ранние ранги десятков игроков засыпят чат). «Прославленная» и выше.
ANNOUNCE_RANK_FROM = 3


def rank(reputation: int) -> int:
    """Индекс ранга по репутации: наибольший порог ≤ rep."""
    rep = max(0, int(reputation or 0))
    r = 0
    for i, (thr, *_ ) in enumerate(FAME_RANKS):
        if rep >= thr:
            r = i
    return r


def title(reputation: int) -> str:
    return FAME_RANKS[rank(reputation)][1]


def income_mult(reputation: int) -> float:
    """Множитель ГОСТЕВОГО дохода от ранга (1.00…1.55). Только розница — не
    пассив (не раздуваем оффлайн-накопление); петля живёт в активной игре."""
    return FAME_RANKS[rank(reputation)][2]


def income_pct(reputation: int) -> int:
    return round((income_mult(reputation) - 1) * 100)


def reward_gold(rank_idx: int) -> int:
    """Разовая награда за достижение ранга (0 у стартового)."""
    if 0 <= rank_idx <= MAX_RANK:
        return FAME_RANKS[rank_idx][3]
    return 0


# ── Ф2: знатные гости ─────────────────────────────────────────────────────
# Чем славнее кабак, тем чаще заглядывает знатная особа и тем щедрее её чаевые
# (доля от выручки сделки). Чаевые — БОНУС сверх базы (как «фарт» вылазок): база
# гарантирована и равна предпросмотру (retail_total), чаевые помечаются отдельно.
# Индекс = ранг (0..6). Ожидаемое среднее сверх базы: топ ≈ 0.30×0.35 = +10%.
_NOBLE_CHANCE: tuple[float, ...] = (0.0, 0.03, 0.06, 0.10, 0.15, 0.22, 0.30)
_NOBLE_TIP: tuple[float, ...] = (0.0, 0.12, 0.15, 0.18, 0.22, 0.28, 0.35)


def noble_chance(rank_idx: int) -> float:
    """Шанс, что при сбыте гостям заглянет знатная особа (0 на дне ранга)."""
    return _NOBLE_CHANCE[rank_idx] if 0 <= rank_idx <= MAX_RANK else 0.0


def noble_tip(rank_idx: int) -> float:
    """Доля выручки сделки, что знатный гость отсыпает чаевыми."""
    return _NOBLE_TIP[rank_idx] if 0 <= rank_idx <= MAX_RANK else 0.0


def noble_tip_gold(reputation: int, base_gold: int, rng) -> int:
    """Чаевые знатного гостя за конкретную сделку: 0 если не зашёл (rng), иначе
    доля выручки по рангу (≥1). ЕДИНАЯ котировка для начисления и показа."""
    r = rank(reputation)
    if base_gold <= 0 or rng.random() >= noble_chance(r):
        return 0
    return max(1, round(base_gold * noble_tip(r)))


def next_at(reputation: int) -> int | None:
    """Порог следующего ранга (None — уже вершина)."""
    r = rank(reputation)
    return None if r >= MAX_RANK else FAME_RANKS[r + 1][0]


def progress(reputation: int) -> tuple[int, int, int]:
    """(процент 0..100 до следующего ранга, осталось репутации, порог следующего).
    На вершине — (100, 0, текущий порог)."""
    rep = max(0, int(reputation or 0))
    r = rank(reputation)
    cur = FAME_RANKS[r][0]
    nxt = next_at(reputation)
    if nxt is None:
        return 100, 0, cur
    span = max(1, nxt - cur)
    pct = max(0, min(100, round((rep - cur) * 100 / span)))
    return pct, max(0, nxt - rep), nxt


def dto(tavern) -> dict:
    """Снимок славы для мини-аппа: ранг, титул, бонус дохода, прогресс до след."""
    rep = int(getattr(tavern, "reputation", 0) or 0)
    r = rank(rep)
    pct, left, nxt = progress(rep)
    return {
        "rank": r, "title": FAME_RANKS[r][1], "income_pct": income_pct(rep),
        "rep": rep, "top": r >= MAX_RANK,
        "next_at": nxt if r < MAX_RANK else None,
        "next_title": FAME_RANKS[r + 1][1] if r < MAX_RANK else None,
        "progress": pct, "remaining": left,
        "noble_chance": round(noble_chance(r) * 100),   # 🎩 знатные гости: шанс на сбыте
        "noble_tip": round(noble_tip(r) * 100),
    }


def badge(reputation: int) -> dict | None:
    """Компактный престиж-бейдж ранга для ПУБЛИЧНЫХ витрин (рейтинг, карта, профиль).
    None на «Безвестной дыре» (ранг 0) — не засоряем безымянных. ЕДИНАЯ котировка:
    ранг из той же fame.rank, что и бонус/титул (показ=действие престижа)."""
    r = rank(reputation)
    if r <= 0:
        return None
    return {"rank": r, "title": FAME_RANKS[r][1]}


def pop_rankups(tavern) -> list[int]:
    """Забрать НОВЫЕ достигнутые ранги (для события/награды) и поднять HWM.
    Возвращает индексы [prev+1 … cur] один раз — при следующем вызове пусто, пока
    не вырастет ещё. Мутирует ТОЛЬКО tavern.fame_rank; награду/анонс — вызывающий
    (под локом). Репутация может падать (сюжет) — HWM не опускаем, награду не
    отбираем; титул/бонус следуют ТЕКУЩЕЙ репутации (см. dto/income_mult)."""
    cur = rank(int(getattr(tavern, "reputation", 0) or 0))
    have = int(getattr(tavern, "fame_rank", 0) or 0)
    if cur <= have:
        return []
    tavern.fame_rank = cur
    return list(range(have + 1, cur + 1))
