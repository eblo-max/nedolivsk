"""Перки за стояние у фракций: дружба начинает платить в экономике.

Завязано на личную репутацию фракций (story.faction) и флаг гильдии.
Читатели — city.effects (иммунитеты к ситуациям), доход (бонус сбыта),
найм бригад (скидка), экран горожан (показ активных перков).
"""

from bot.db.models import Player
from bot.game import balance, story_state

_T = balance.PERK_THRESHOLD


def _fac(player: Player, fac: str) -> int:
    return story_state.faction(player, fac)


def _friend(player: Player, fac: str) -> bool:
    return _fac(player, fac) >= _T


def is_guild(player: Player) -> bool:
    return story_state.has_flag(player, "guild_member")


# ── Иммунитеты к городским ситуациям ───────────────────────────────────
def thieves_skim_immune(player: Player) -> bool:
    """Воры не обирают: свои гильдии, друзья воров или под защитой стражи."""
    return is_guild(player) or _friend(player, "thieves") or _friend(player, "watch")


def crown_tax_immune(player: Player) -> bool:
    """Поборы короны не страшны: грамота короны или воры прячут деньги."""
    return _friend(player, "crown") or _friend(player, "thieves")


def temperance_immune(player: Player) -> bool:
    """Пост нипочём — паства церковного друга всё равно приходит."""
    return _friend(player, "church")


def curfew_immune(player: Player) -> bool:
    """Комендантский час не бьёт — стража пускает своего (или с грамотой)."""
    return _friend(player, "watch") or story_state.has_flag(player, "law_friend")


# ── Арк-перки (вечные награды личных линий NPC, фаза 4a) ────────────────
def _has(player: Player, flag: str) -> bool:
    return story_state.has_flag(player, flag)


def passive_mult(player: Player) -> float:
    """Знатные завсегдатаи (арка Бухло) — больше пассивного дохода."""
    return 1.05 if _has(player, "noble_patrons") else 1.0


def food_mult(player: Player) -> float:
    """Домашняя кухня (арка Параски) — еду берут охотнее."""
    return 1.10 if _has(player, "home_cooking") else 1.0


def has_fame(player: Player) -> bool:
    """Знаменитый кабак (арка Лютика) — слава капает репутацией со сбыта."""
    return _has(player, "famous_tavern")


def luck_bonus(player: Player) -> int:
    """Талисман удачи (арка Алхимика) — счастливые вылазки чаще."""
    return 5 if _has(player, "lucky_charm") else 0


# ── Пассивные перки экономики ──────────────────────────────────────────
def demand_bonus(player: Player) -> float:
    """Купеческая протекция — множитель сбыта (всегда)."""
    return balance.PERK_MERCHANT_DEMAND if _friend(player, "merchants") else 1.0


def expedition_pay_mult(player: Player) -> float:
    """Воровские связи — дешевле нанимать бригады. «Свой» (арка Скупщика) —
    ещё дешевле."""
    if story_state.has_flag(player, "made_man"):
        return 0.75
    if _friend(player, "thieves") or is_guild(player):
        return balance.PERK_THIEVES_EXPEDITION
    return 1.0


# ── Для показа на экране горожан ───────────────────────────────────────
def active_perks(player: Player) -> list[str]:
    out: list[str] = []
    if _friend(player, "merchants"):
        out.append("💰 Купеческая протекция: +15% к сбыту")
    if _friend(player, "watch"):
        out.append("👮 Под крылом стражи: ни воров, ни комендантского часа")
    if _has(player, "made_man"):
        out.append("🥷 Верхушка гильдии: деньги не отнять, наём −25%")
    elif _friend(player, "thieves") or is_guild(player):
        out.append("🥷 Свои у воров: деньги не отнять, наём −15%")
    if _friend(player, "crown"):
        out.append("👑 Королевская грамота: поборы не страшны")
    if _friend(player, "church"):
        out.append("⛪ Благословение: пост нипочём")
    # Арк-перки (вечные награды личных линий)
    if _has(player, "noble_patrons"):
        out.append("🛡 Знатные завсегдатаи: +5% пассивного дохода")
    if _has(player, "famous_tavern"):
        out.append("🎻 Знаменитый кабак: слава капает репутацией со сбыта")
    if _has(player, "home_cooking"):
        out.append("🧹 Домашняя кухня: +10% к продаже еды")
    if _has(player, "lucky_charm"):
        out.append("⚗️ Талисман удачи: счастливые вылазки чаще")
    if _has(player, "law_friend"):
        out.append("👮 Грамота доверия: комендантский час нипочём")
    if _has(player, "trade_partner"):
        out.append("💰 Совладелец торгового дома: купеческая лига за спиной")
    return out
