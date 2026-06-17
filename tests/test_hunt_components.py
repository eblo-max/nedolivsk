"""Фаза 2 — компоненты и петля крафта: звери роняют компоненты, из них куётся
снаряга среднего звена, и эта снаряга закрывает обрыв сложности (вожак/медведь/
разбойник из стены 0% выходят в середину на «тесак★»).
"""
import random
import statistics

from bot.game import balance, combat, items


def _loot_yields(enemy_id: str, comp: str, rolls: int = 400) -> bool:
    """Хоть раз ли падает компонент comp с зверя за rolls попыток (с победы)."""
    rng = random.Random(1)
    enemy = combat.ENEMY[enemy_id]
    return any(comp in combat.roll_loot(enemy, 0, rng)["res"] for _ in range(rolls))


def test_components_drop_from_right_beasts():
    assert _loot_yields("medved", "hide")    # медведь — прайм-шкура
    assert _loot_yields("volk", "fang")      # волк — клык
    assert _loot_yields("olen", "sinew")     # олень — жилы
    assert _loot_yields("ataman", "ring")    # атаман — перстень-диковина


def test_trophies_are_now_real_components_not_cosmetic():
    # бывшие косметические трофеи (label) заменены на компоненты-ресурсы
    for eid in ("vozhak", "razboy", "ataman"):
        labels = [d.label for d in combat.ENEMY[eid].drops if not d.res]
        assert not labels, f"{eid} всё ещё роняет косметический трофей"


def test_component_gear_exists_and_craftable():
    for iid in ("fur_coat", "fang_cleaver", "swift_boots", "prestige_ring"):
        item = items.CATALOG[iid]
        assert item.craftable
        # стоимость включает охот-компонент
        assert any(k in balance.HUNT_COMPONENTS for k in item.cost)


def test_components_named_everywhere():
    # имя/эмодзи подхватываются общим лукапом (склад/крафт/дроп не покажут сырой ключ)
    for comp in balance.HUNT_COMPONENTS:
        assert comp in balance.GOODS_NAMES and comp in balance.GOODS_EMOJI
        assert comp in balance.RESOURCE_PRICE      # учитывается в ВВП


def _wr(equip, enemy_id, n=400, seed=1):
    stats = dict(items.combat_stats(equip))
    return combat.forecast(stats, combat.ENEMY[enemy_id], balance.BASE_HP,
                           n=n, rng=random.Random(seed))[0]


TESAK = {"weapon": "fang_cleaver:1", "chest": "fur_coat:1",
         "left_hand": "oak_shield:1", "head": "leather_cap:1"}
KOVSH = {"weapon": "kovsh:1", "chest": "fartuk:1",
         "left_hand": "oak_shield:1", "head": "leather_cap:1"}


def test_component_gear_fills_the_cliff():
    # на ковш★ медведь/разбойник — стена; компонент-«тесак★» выводит их в середину
    for eid in ("medved", "razboy"):
        assert _wr(KOVSH, eid) <= 15
        assert 25 <= _wr(TESAK, eid) <= 80, f"{eid} не в середине на тесак★"


def test_component_gear_weaker_than_boss_top():
    # тесак★★★ слабее клыка дракона ★★★ — боссовая снаряга остаётся вершиной
    fang3 = items.combat_stats({"weapon": "fang_cleaver:3"})["damage"]
    dragon3 = items.combat_stats({"weapon": "dragon_fang:3"})["damage"]
    assert fang3 < dragon3


# ── Фаза 3: редкие элиты ────────────────────────────────────────────────
def _wr_enemy(equip, enemy, n=600, seed=1):
    stats = dict(items.combat_stats(equip))
    return combat.forecast(stats, enemy, balance.BASE_HP, n=n, rng=random.Random(seed))[0]


def test_elite_roll_respects_chance(monkeypatch):
    monkeypatch.setattr(balance, "HUNT_ELITE_CHANCE", 100)
    assert combat.maybe_elite("olen", random.Random(1)).id == "olen_gold"
    assert combat.maybe_elite("zayac", random.Random(1)) is None   # не у всех есть элита
    monkeypatch.setattr(balance, "HUNT_ELITE_CHANCE", 0)
    assert combat.maybe_elite("olen", random.Random(1)) is None


def test_elite_is_jackpot_not_trap():
    """Элита бьётся той же снарягой, что и базовый (винрейт ≈ базовому, не 0%),
    и даёт больше золота — позитивный сюрприз, а не ловушка."""
    kit = {"weapon": "kovsh:1", "chest": "fartuk:1",
           "left_hand": "oak_shield:1", "head": "leather_cap:1"}
    for base_id, elite in combat.ELITES.items():
        base_wr = _wr_enemy(kit, combat.ENEMY[base_id])
        if base_wr < 60:
            continue   # сравниваем там, где базовый уверенно бьётся
        assert _wr_enemy(kit, elite) >= base_wr - 25, f"{elite.id} — ловушка"
        assert elite.gold[0] > combat.ENEMY[base_id].gold[1]   # золота заметно больше


def test_elite_drops_guaranteed_components_and_rare_ring():
    rng = random.Random(2)
    el = combat.ELITES["olen"]
    got_comp = got_ring = False
    for _ in range(300):
        res = combat.roll_loot(el, 0, rng)["res"]
        got_comp = got_comp or res.get("hide", 0) > 0
        got_ring = got_ring or res.get("ring", 0) > 0
    assert got_comp and got_ring


# ── Фаза 4: регионализация ──────────────────────────────────────────────
REGION_BEAST = {"north_wilds": "lynx", "green_valleys": "tusker", "red_wastes": "scorpion"}


def test_region_filter_shows_common_plus_own_beast():
    common = [e.id for e in combat.ENEMIES if not e.region]
    for region, beast in REGION_BEAST.items():
        ids = [e.id for e in combat.huntable(region)]
        assert set(common) <= set(ids)                 # все общие доступны
        assert beast in ids                            # свой региональный — да
        others = {b for r, b in REGION_BEAST.items() if r != region}
        assert not (others & set(ids))                 # чужие региональные — нет


def test_regional_beasts_drop_unique_component():
    comp = {"lynx": "pelt", "tusker": "tusk", "scorpion": "chitin"}
    for bid, c in comp.items():
        rng = random.Random(3)
        assert any(c in combat.roll_loot(combat.ENEMY[bid], 0, rng)["res"]
                   for _ in range(400))


def test_regional_belts_parity_identical_stats():
    belts = ("lynx_belt", "tusk_belt", "chitin_belt")
    stats = [tuple(sorted(items.combat_stats({"belt": f"{b}:1"}).items())) for b in belts]
    assert len(set(stats)) == 1                        # статы ИДЕНТИЧНЫ (паритет)
    # каждый требует компонент своего региона
    for b, c in zip(belts, ("pelt", "tusk", "chitin"), strict=True):
        assert c in items.CATALOG[b].cost


def test_regional_beasts_difficulty_parity():
    """Сложность троих региональных — в узкой полосе (паритет усилия за компонент)."""
    kit = {"weapon": "fang_cleaver:1", "chest": "fur_coat:1",
           "left_hand": "oak_shield:1", "head": "leather_cap:1"}
    wrs = [_wr_enemy(kit, combat.ENEMY[b]) for b in REGION_BEAST.values()]
    assert max(wrs) - min(wrs) <= 15, f"асимметрия регионов: {wrs}"


# ── Фаза 5: черты-слабости ──────────────────────────────────────────────
from dataclasses import replace  # noqa: E402


def _wc(stats, enemy):
    return combat.win_chance(stats, enemy)


def test_venom_bypasses_player_armor():
    """Ядовитый бьёт сквозь броню: армор НЕ помогает против него (а против
    обычного — помогает)."""
    base = replace(combat.ENEMY["kaban"], traits=())
    venom = replace(base, traits=("venom",))
    naked = {"damage": 10}
    armored = {"damage": 10, "armor": 30}
    # против обычного броня заметно поднимает шанс
    assert _wc(armored, base) > _wc(naked, base) + 0.05
    # против ядовитого броня почти не помогает (бьёт сквозь)
    assert _wc(armored, venom) < _wc(armored, base)            # ядовитый опаснее
    assert abs(_wc(armored, venom) - _wc(naked, venom)) < 0.05  # броня ≈ бесполезна


def test_evasive_reduces_player_damage():
    """Увёртливый уводит часть ударов → шанс ниже, чем у идентичного обычного."""
    base = replace(combat.ENEMY["olen"], traits=())
    evasive = replace(base, traits=("evasive",))
    stats = {"damage": 10, "armor": 10}
    assert _wc(stats, evasive) < _wc(stats, base)


def test_brief_shows_trait_weakness():
    from types import SimpleNamespace
    from bot import texts
    p = SimpleNamespace(equipment={"weapon": "kovsh:1"}, hp=35, hp_at=None,
                        buff_kind=None, buff_until=None, tavern=None, region="red_wastes")
    assert "Ядовит" in texts.hunt_detail(p, combat.ENEMY["scorpion"])
    assert "Увёртлив" in texts.hunt_detail(p, combat.ENEMY["lynx"])


def test_resolve_animation_reflects_traits():
    """Аудит-фикс: анимация боя честна к чертам — ядовитый бьёт сквозь броню,
    увёртливый даёт промахи."""
    rng = random.Random(3)
    st = {"damage": 14, "armor": 30}
    seen_miss = any(r.get("miss") for _ in range(80)
                    for r in combat.resolve({"damage": 14}, combat.ENEMY["volk"],
                                            balance.BASE_HP, rng).log)
    assert seen_miss
    venom_ed = [r["ed"] for _ in range(300)
                for r in combat.resolve(st, combat.ENEMY["scorpion"], balance.BASE_HP, rng).log
                if r["ed"] > 0]
    plain = replace(combat.ENEMY["scorpion"], traits=())
    plain_ed = [r["ed"] for _ in range(300)
                for r in combat.resolve(st, plain, balance.BASE_HP, rng).log if r["ed"] > 0]
    assert statistics.mean(venom_ed) > statistics.mean(plain_ed)   # яд сквозь броню


def test_forge_hides_other_region_belts():
    from types import SimpleNamespace
    from bot.keyboards.inline import forge_kb
    p = SimpleNamespace(equipment={}, region="north_wilds")
    txts = [b.text.lower() for row in forge_kb(p).inline_keyboard for b in row]
    assert any("рысь" in t for t in txts)                       # свой пояс — есть
    assert not any("клык" in t or "хитин" in t for t in txts)   # чужих нет
