"""Фракции Недоливска. Репутация фракций — на игроке (story.faction),
сила фракций в городе — на CityState.faction_power.

РАНГИ И ЗУБЫ (живой мир, фаза 1): репутация конвертируется в ранг, ранг даёт
механические эффекты. Правило «показ = действие»: эффекты берутся ТОЛЬКО из
котировок ниже — и механикой, и экраном Репутации."""

NAMES: dict[str, str] = {
    "watch": "Стража",
    "thieves": "Воровская гильдия",
    "merchants": "Купеческая лига",
    "church": "Церковь",
    "crown": "Корона",
}

# Пороги рангов: (минимум репутации, ранг, звание). Дружба не гниёт (без decay),
# вражда искупается делами. Порядок — от лучшего к худшему.
RANKS: list[tuple[int, int, str]] = [
    (75, 3, "легенда"),
    (40, 2, "побратим"),
    (15, 1, "свой"),
    (-14, 0, "нейтрал"),
    (-39, -1, "недруг"),
    (-10**9, -2, "враг"),
]

# Зубы фракций (за ранг, линейно; вражда — те же формулы в минус):
MERCHANT_PRICE_PCT = 3     # лига: % к ценам лавки/вилки торга за ранг
THIEF_SNEAK_P = 0.02       # воры: шанс «тишком» в ночной ходке за ранг
THIEF_NIGHT_SALE_PCT = 2   # воры: % к ценам лавки НОЧЬЮ (22–6 МСК) за ранг
WATCH_PICKPOCKET_PCT = 20  # стража: на сколько % меньше крадут карманники за ранг
WATCH_BUST_KEEP_PCT = 12   # стража: % котомки, отбитой при бюсте ходки, за ранг


def name(fac_id: str) -> str:
    return NAMES.get(fac_id, fac_id)


def rank(player, fac_id: str) -> int:
    """Ранг фракции по репутации игрока (story.faction). Терпим к фейкам без story."""
    st = getattr(player, "story", None) or {}
    return rank_of(int(st.get("faction", {}).get(fac_id, 0)))


def rank_of(rep: int) -> int:
    for lo, r, _label in RANKS:
        if rep >= lo:
            return r
    return -2


def rank_label(r: int) -> str:
    for _lo, rr, label in RANKS:
        if rr == r:
            return label
    return "нейтрал"


# ── Котировки эффектов (единый источник для механик и экрана) ──────────────
def merchant_price_mult(player) -> float:
    """Лига: множитель цен продажи в лавке и вилке торга (±3%/ранг)."""
    return 1 + MERCHANT_PRICE_PCT * rank(player, "merchants") / 100


def thief_sneak_bonus(player) -> float:
    """Воры: прибавка шанса «тишком» в ночной ходке (только дружба)."""
    return THIEF_SNEAK_P * max(0, rank(player, "thieves"))


def thief_night_sale_mult(player, msk_hour: int) -> float:
    """Воры: ночью (22–6 МСК) лавка берёт дороже у своих (+2%/ранг)."""
    if msk_hour >= 22 or msk_hour < 6:
        return 1 + THIEF_NIGHT_SALE_PCT * max(0, rank(player, "thieves")) / 100
    return 1.0


def watch_pickpocket_mult(player) -> float:
    """Стража: карманники крадут меньше у друзей стражи (−20%/ранг, пол 0.2)."""
    return max(0.2, 1 - WATCH_PICKPOCKET_PCT * max(0, rank(player, "watch")) / 100)


def watch_bust_keep_pct(player) -> float:
    """Стража: доля котомки, отбитая при бюсте ходки (12%/ранг, кап 36%)."""
    return min(0.36, WATCH_BUST_KEEP_PCT * max(0, rank(player, "watch")) / 100)


def perk_lines(player, fac_id: str) -> list[str]:
    """Строки перков для экрана Репутации — из ТЕХ ЖЕ котировок."""
    r = rank(player, fac_id)
    out: list[str] = []
    if fac_id == "merchants" and r != 0:
        pct = MERCHANT_PRICE_PCT * r
        out.append(f"{'+' if pct > 0 else ''}{pct}% к ценам лавки и торга")
    if fac_id == "thieves" and r > 0:
        out.append(f"+{int(THIEF_SNEAK_P * r * 100)}% к «тишком» в ночной ходке")
        out.append(f"+{THIEF_NIGHT_SALE_PCT * r}% к ночной скупке (22–6 МСК)")
    if fac_id == "watch" and r > 0:
        out.append(f"карманники крадут на {WATCH_PICKPOCKET_PCT * r}% меньше")
        out.append(f"при провале ходки стража отбивает {WATCH_BUST_KEEP_PCT * r}% котомки")
    return out
