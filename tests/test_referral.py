"""Зазывала (рефералка): награда за активацию — один раз, тиры, без само-зазыва."""

import asyncio

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from bot.db import repo
from bot.db.models import Base, Player
from bot.game import balance


@compiles(JSONB, "sqlite")  # SQLite не знает JSONB — мапим в JSON для теста
def _jsonb_as_json(type_, compiler, **kw):
    return "JSON"


async def _run(n_invites: int = 1, *, self_ref: bool = False, double: bool = False) -> dict:
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sf() as s:
            inviter = await repo.create_player(s, 1, "inv", "Зазывала")
            g0, r0 = inviter.gold, inviter.reputation
            results = []
            for k in range(n_invites):
                pid = 100 + k
                new = await repo.create_player(s, pid, f"n{k}", f"Новичок{k}")
                new.referred_by = pid if self_ref else 1
                results.append(await repo.grant_referral_rewards(s, new))
                if double:                       # повторная выдача тому же — должна быть None
                    results.append(await repo.grant_referral_rewards(s, new))
            await s.commit()
            inviter = await s.get(Player, 1)
            first = await s.get(Player, 100)
            return {
                "gold_delta": inviter.gold - g0,
                "rep_delta": inviter.reputation - r0,
                "ref_tier": inviter.ref_tier,
                "results": results,
                "invitee_gold": first.gold,        # 100 (дефолт) + подъёмные
                "invitee_rewarded": first.ref_rewarded,
            }
    finally:
        await eng.dispose()


def test_single_invite_pays_both_once():
    r = asyncio.run(_run(1))
    assert r["gold_delta"] == balance.REFERRAL_INVITER_GOLD          # +300 пригласившему
    assert r["rep_delta"] == balance.REFERRAL_INVITER_REP            # +5 репутации
    assert r["invitee_gold"] == 100 + balance.REFERRAL_INVITEE_GOLD  # новичку подъёмные
    assert r["invitee_rewarded"] is True
    assert r["results"][0] == {"invitee_gold": balance.REFERRAL_INVITEE_GOLD}


def test_no_double_pay():
    r = asyncio.run(_run(1, double=True))
    assert r["gold_delta"] == balance.REFERRAL_INVITER_GOLD          # только один раз
    assert r["results"][1] is None                                  # повтор — ничего


def test_self_referral_ignored():
    r = asyncio.run(_run(1, self_ref=True))
    assert r["gold_delta"] == 0                                     # сам себя не зазвать
    assert r["results"][0] is None


def test_tier_bonus_at_threshold():
    need, bonus = balance.REFERRAL_TIERS[0]                          # первая веха (5, 500)
    r = asyncio.run(_run(need))
    # need × базовая выдача + один тир-бонус за прохождение вехи
    assert r["gold_delta"] == need * balance.REFERRAL_INVITER_GOLD + bonus
    assert r["ref_tier"] == 1
