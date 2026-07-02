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


def shop_buy_mult(player) -> float:
    """Лига: закуп в лавке скупщика — друзьям дешевле, врагам дороже (зеркало торга)."""
    return max(0.85, 2 - merchant_price_mult(player))


def thief_sneak_bonus(player) -> float:
    """Воры: «тишком» в ночной ходке. Дружба помогает, ВРАЖДА мешает —
    осведомители гильдии сдают тебя первым же патрулям."""
    return THIEF_SNEAK_P * rank(player, "thieves")


def thief_night_sale_mult(player, msk_hour: int) -> float:
    """Воры: ночью (22–6 МСК) лавка берёт дороже у своих (+2%/ранг)."""
    if msk_hour >= 22 or msk_hour < 6:
        return 1 + THIEF_NIGHT_SALE_PCT * rank(player, "thieves") / 100
    return 1.0


def watch_pickpocket_mult(player) -> float:
    """Стража: у друзей карманники крадут меньше (−20%/ранг), у ВРАГОВ — больше
    (стража «не замечает», как тебя щиплют). Коридор 0.2…1.5."""
    return min(1.5, max(0.2, 1 - WATCH_PICKPOCKET_PCT * rank(player, "watch") / 100))


WATCH_HOSTILE_P = 0.03     # враг стражи: штраф шанса ЛЮБОГО шага ходки за ранг вражды


def watch_hostile_penalty(player) -> float:
    """Враг стражи: патрули знают тебя в лицо — вся ночная ходка опаснее."""
    return WATCH_HOSTILE_P * max(0, -rank(player, "watch"))


def watch_bust_keep_pct(player) -> float:
    """Стража: доля котомки, отбитая при бюсте ходки (12%/ранг, кап 36%)."""
    return min(0.36, WATCH_BUST_KEEP_PCT * max(0, rank(player, "watch")) / 100)


def perk_lines(player, fac_id: str) -> list[str]:
    """Строки перков для экрана Репутации — из ТЕХ ЖЕ котировок."""
    r = rank(player, fac_id)
    out: list[str] = []
    if fac_id == "merchants" and r != 0:
        pct = MERCHANT_PRICE_PCT * r
        out.append(f"торг: цена {'выше' if pct > 0 else 'ниже'} на {abs(pct)}%")
        out.append(f"лавка: закуп {'дешевле' if pct > 0 else 'дороже'} на {abs(pct)}%")
    if fac_id == "thieves" and r != 0:
        s = int(THIEF_SNEAK_P * r * 100)
        out.append(f"{'+' if s > 0 else ''}{s}% к «тишком» в ночной ходке")
        out.append(f"{'+' if r > 0 else ''}{THIEF_NIGHT_SALE_PCT * r}% к ночной скупке (22–6 МСК)")
    if fac_id == "watch":
        if r > 0:
            out.append(f"карманники крадут на {WATCH_PICKPOCKET_PCT * r}% меньше")
            out.append(f"при провале ходки стража отбивает {WATCH_BUST_KEEP_PCT * r}% котомки")
        elif r < 0:
            out.append(f"карманники крадут на {WATCH_PICKPOCKET_PCT * -r}% БОЛЬШЕ — стража не замечает")
            out.append(f"патрули знают тебя в лицо: вся ночная ходка опаснее на {int(WATCH_HOSTILE_P * -r * 100)}%")
    return out
