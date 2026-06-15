"""Аудит производственной маржи: для КАЖДОГО товара на уровнях 1..10 считает
чистую прибыль (выручка − плата бригадам за добычу входов, с учётом передела) и
прибыль/час. Цель: ни одна производственная активность не должна быть убыточной.

Запуск: python -m scripts.audit_production_margin
"""

import math
import sys

from bot.game import balance, buildings, production as prod

REGION = "green_valleys"  # нейтрально-усреднённая зона для оценки (без крайностей)


def ucost(r: int, L: int) -> float:
    """Плата бригаде за единицу ресурса r на уровне L (нейтральная добыча)."""
    base, per = balance.EXPEDITION_YIELD[r]
    y = base + per * balance.YIELD_LEVEL_GROWTH * (L - 1)  # без региональных мультов
    return balance.worker_pay(L) / y


def input_cost(r: str, qty: int, L: int) -> float:
    """Себестоимость входа: сырьё — напрямую; полуфабрикат — через передел."""
    if r in ("malt", "flour"):                 # мельница: 10L зерна -> 8L
        runs = math.ceil(qty / (8 * L))
        return runs * 10 * L * ucost("grain", L)
    if r == "ingot":                            # горн: 6L руды -> 4L
        runs = math.ceil(qty / (4 * L))
        return runs * 6 * L * ucost("ore", L)
    return qty * ucost(r, L)


def margin(inputs: dict, out: int, hours: int, price: int, L: int):
    cost = sum(input_cost(r, q, L) for r, q in inputs.items())
    rev = out * price
    return rev - cost, (rev - cost) / hours


# (название, функция_входов, функция_выхода, часы, цена)
def products():
    P = prod
    items = []
    for t in (1, 2, 3):
        items.append((f"эль{'★' * t}",
                      lambda L, t=t: P.brew_inputs(t, L), lambda L, t=t: P.brew_output(t, L),
                      P.brew_hours(t), P.ALE_PRICE[t]))
    for rc in P.MEADERY:
        items.append((P.DRINKS[rc].name, lambda L, rc=rc: P.meadery_inputs(rc, L),
                      lambda L, rc=rc: P.meadery_output(rc, L), P.meadery_hours(rc),
                      P.DRINKS[rc].price))
    items.append(("вино", lambda L: P.winery_inputs("wine", L),
                  lambda L: P.winery_output("wine", L), P.winery_hours("wine"), P.GOODS["wine"].price))
    items.append(("жаркое", lambda L: P.kitchen_inputs("roast", L),
                  lambda L: P.kitchen_output("roast", L), P.kitchen_hours("roast"), P.GOODS["roast"].price))
    for b, recs in P.RECIPES.items():
        for rc in recs:
            items.append((P.GOODS[rc].name, lambda L, b=b, rc=rc: P.recipe_inputs(b, rc, L),
                          lambda L, b=b, rc=rc: P.recipe_output(b, rc, L),
                          P.recipe_hours(b, rc), P.GOODS[rc].price))
    return items


def main() -> int:
    levels = list(range(1, 11))
    print(f"Множитель прироста добычи: ×{balance.YIELD_LEVEL_GROWTH}\n")
    print("Чистыми/час по товарам (— = УБЫТОК):")
    hdr = f"{'товар':16}" + "".join(f"ур{L:>2}" for L in levels)
    print(hdr)
    worst = (10**9, "", 0)
    for name, fin, fout, hours, price in products():
        cells = ""
        for L in levels:
            net, nph = margin(fin(L), fout(L), hours, price, L)
            if net < worst[0]:
                worst = (net, name, L)
            cells += f"{nph:>4.0f}"
        print(f"{name:16}{cells}")

    print()
    ok = worst[0] >= 0
    print(f"{'✅' if ok else '❌'} Минимальная маржа: {worst[0]:.0f} "
          f"({worst[1]}, ур.{worst[2]}) — {'все товары прибыльны' if ok else 'ЕСТЬ УБЫТОК'}")

    # Окупаемость пристроек (по марже их профильного товара)
    print("\nОкупаемость пристроек (часов активной работы профильного товара):")
    cases = [("brewery", "эль★", lambda L: prod.brew_inputs(1, L), lambda L: prod.brew_output(1, L),
              prod.brew_hours(1), 5),
             ("winery", "вино", lambda L: prod.winery_inputs("wine", L),
              lambda L: prod.winery_output("wine", L), prod.winery_hours("wine"), 15),
             ("dairy", "сыр", lambda L: prod.recipe_inputs("dairy", "cheese", L),
              lambda L: prod.recipe_output("dairy", "cheese", L), prod.recipe_hours("dairy", "cheese"), 12)]
    for bid, pname, fin, fout, hours, price in cases:
        g = buildings.CATALOG[bid].cost["gold"]
        for L in (3, 5):
            _, nph = margin(fin(L), fout(L), hours, price, L)
            pb = g / nph if nph > 0 else float("inf")
            print(f"  {buildings.CATALOG[bid].name} ({g}g) · {pname} ур.{L}: "
                  f"~{nph:.0f}g/ч → {pb:.0f}ч (без учёта розницы и пассива — реально быстрее)")

    print()
    if not ok:
        print("❌ ПРОВАЛ: есть убыточные товары")
        return 1
    print("✅ Все производственные активности прибыльны на ур.1–10")
    return 0


sys.exit(main())
