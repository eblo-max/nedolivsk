"""Ф2b-полировка: эксклюзив-фляги оживлены в РЕЙДЕ и НОЧНОЙ ХОДКЕ.

Раньше hp/уворот-фляги были мертвы вне охоты (raid.flask_mods читал только
dmg/crit/antidote; nightrun.FLASK_APPROACH не знал новых ключей). Теперь:
 • рейд конвертирует hp/уворот в урон (нет HP игрока в DPS-гонке);
 • ходка знает эксклюзивы по подходу + hp-фляги дают стартовую выносливость.
"""

import os
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "test:test")

from bot.game import balance as bal, combat, nightrun as nr, raid  # noqa: E402


def _player(lvl=5):
    return NS(level=lvl, gold=0, equipment={}, region="green_valleys", inventory={},
              buff_kind=None, buff_until=None, perks={}, hp=None, hp_at=None,
              tavern=NS(products={}, capacity=20, reputation=0))


# ── РЕЙД ────────────────────────────────────────────────────────────────
def test_raid_flask_hp_and_dodge_become_damage():
    """hp/уворот-фляги дают урон в рейде (сытый/ловкий бьёт крепче); dmg/crit/antidote — как есть."""
    assert raid.flask_mods(["zodchy_feast"])["dmg"] == 45 // raid.RAID_HP_TO_DMG      # 15
    ml = raid.flask_mods(["mason_loaf"])
    assert ml["dmg"] == 28 // raid.RAID_DODGE_TO_DMG and ml["antidote"] is True        # 7 + антидот
    assert raid.flask_mods(["thunder_sbiten"])["dmg"] == 22                            # прямой урон
    assert raid.flask_mods(["artel_nectar"])["crit"] == 20                             # крит
    # стак складывается
    assert raid.flask_mods(["zodchy_feast", "thunder_sbiten"])["dmg"] == 15 + 22


def test_raid_flask_label_matches_effect():
    """Показ=действие в рейде: метка описывает РОВНО то, что даёт flask_mods."""
    for k in bal.FLASK_EFFECTS:
        m = raid.flask_mods([k])
        lbl = raid.flask_label(k)
        assert (f"+{m['dmg']} урона" in lbl) == (m["dmg"] > 0)
        assert (f"+{m['crit']}% крита" in lbl) == (m["crit"] > 0)
        assert ("снимает проклятье" in lbl) == m["antidote"]
        assert lbl != "—"          # у каждой фляги есть рейд-эффект
    # эксклюзив-«Пир» показывает урон, а не «+45❤» (что в рейде было бы враньём)
    assert raid.flask_label("zodchy_feast") == "+15 урона"


def test_raid_feast_raises_actual_hit():
    """Пир зодчих реально поднимает урон по боссу (был 0)."""
    import random
    p = _player()
    def avg(keys):
        rng = random.Random(1); m = raid.flask_mods(keys)
        return sum(raid.player_damage(p, rng, m)[0] for _ in range(3000)) / 3000
    assert avg(["zodchy_feast"]) > avg([]) + 8, "feast должен заметно поднять урон"


# ── НОЧНАЯ ХОДКА ────────────────────────────────────────────────────────
def test_nightrun_hp_flask_gives_stamina():
    """hp-фляги (Пир зодчих/жаркое) поднимают стартовый HP ходки."""
    p = _player()
    base = combat.max_hp(p)
    assert nr._flask_hp_bonus(["zodchy_feast"]) == bal.FLASK_EFFECTS["zodchy_feast"]["hp"]
    run = nr.start(p, "green_valleys", flask=["zodchy_feast"])
    assert run["hp"] == base + 45 and run["hp_max"] == base + 45
    assert nr.start(p, "green_valleys", flask=[])["hp"] == base           # без фляги — база


def test_nightrun_exclusive_flasks_in_approach():
    """Эксклюзив-фляги знают свой подход (fight/gamble/sneak)."""
    assert nr.FLASK_APPROACH["thunder_sbiten"] == "fight"
    assert nr.FLASK_APPROACH["artel_nectar"] == "gamble"
    assert nr.FLASK_APPROACH["mason_loaf"] == "sneak"


def test_nightrun_flask_hint_matches_effect():
    """Показ=действие в ходке: хинт = подход (FLASK_APPROACH) и/или выносливость (hp),
    а не урон/крит из FLASK_EFFECTS (что в ходке было бы враньём)."""
    ap_word = {"fight": "смелее в драке", "sneak": "легче тишком", "gamble": "фарт в лихо"}
    for k in bal.FLASK_EFFECTS:
        hint = nr.flask_hint(k)
        ap = nr.FLASK_APPROACH.get(k)
        hp = bal.FLASK_EFFECTS[k].get("hp", 0)
        if k == "sbiten":
            assert hint == "гасит дурноту города"
            continue
        if ap:
            assert ap_word[ap] in hint
        if hp:
            assert f"+{hp} выносливости" in hint
        assert hint != "—"          # каждая фляга что-то делает в ходке
    assert nr.flask_hint("thunder_sbiten") == "смелее в драке"   # не «+22 урона»
    assert nr.flask_hint("zodchy_feast") == "+45 выносливости"   # не «+45 ❤ на бой»


def test_nightrun_approach_bonus_applies_and_is_targeted():
    """Под свой подход — бонус к шансу; под чужой — ничего (gamble не капится потолком)."""
    p = _player()
    run_n = nr.start(p, "green_valleys", flask=["artel_nectar"])
    run_0 = nr.start(p, "green_valleys", flask=[])
    assert nr.success_p(run_n, p, "gamble") > nr.success_p(run_0, p, "gamble")  # свой подход
    # nectar (gamble) в бою (fight) — бонуса нет
    assert nr.success_p(run_n, p, "fight") == nr.success_p(run_0, p, "fight")
