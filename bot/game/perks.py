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
    """Комендантский час не бьёт — стража пускает своего работать."""
    return _friend(player, "watch")


# ── Пассивные перки экономики ──────────────────────────────────────────
def demand_bonus(player: Player) -> float:
    """Купеческая протекция — множитель сбыта (всегда)."""
    return balance.PERK_MERCHANT_DEMAND if _friend(player, "merchants") else 1.0


def expedition_pay_mult(player: Player) -> float:
    """Воровские связи — дешевле нанимать бригады."""
    return balance.PERK_THIEVES_EXPEDITION if (
        _friend(player, "thieves") or is_guild(player)) else 1.0


# ── Для показа на экране горожан ───────────────────────────────────────
def active_perks(player: Player) -> list[str]:
    out: list[str] = []
    if _friend(player, "merchants"):
        out.append("💰 Купеческая протекция: +15% к сбыту")
    if _friend(player, "watch"):
        out.append("👮 Под крылом стражи: ни воров, ни комендантского часа")
    if _friend(player, "thieves") or is_guild(player):
        out.append("🥷 Свой в гильдии: деньги не отнять, бригады дешевле")
    if _friend(player, "crown"):
        out.append("👑 Королевская грамота: поборы не страшны")
    if _friend(player, "church"):
        out.append("⛪ Благословение: пост нипочём")
    return out
