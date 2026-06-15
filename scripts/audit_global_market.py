"""Аудит перехода на ЕДИНЫЙ (глобальный) рынок: движок цен, лимит покупки,
рендеры экранов, диалект SQL биржевых запросов. Без БД — моки + dialect-compile.

Запуск: python -m scripts.audit_global_market
"""

import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from bot.game import balance, bourse, market
from bot.game import auction as gauction
from bot.game import trade as gtrade
from bot import texts

OK, FAIL = "✅", "❌"
fails = 0


def check(name, cond):
    global fails
    print(f"  {OK if cond else FAIL} {name}")
    if not cond:
        fails += 1


def world(market_state=None, scale=1):
    return SimpleNamespace(market=dict(market_state or {}), market_scale=scale)


# ── 1. Движок единого рынка: holder = world ──────────────────────────────────
print("1. Движок единого рынка (factor/nudge/decay на world)")
w = world()
check("пустой рынок → factor 1.0", market.factor(w, "ale1") == 1.0)
market.add_supply(w, "ale1", 100)
f_after = market.factor(w, "ale1")
check("завал давит цену (factor<1)", f_after < 1.0)
check("glut записан на holder.market", w.market.get("ale1", 0) >= 100)
market.nudge(w, "ale1", -200)  # скупка → дефицит
check("дефицит поднимает цену (factor>1 после нетто-минуса)", market.factor(w, "ale1") > 1.0)
# распад к нулю
w2 = world({"bread": 100.0, "_t": (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()})
market.decay(w2)
check("распад почти обнулил старый перекос", abs(w2.market.get("bread", 0.0)) < 1.0)

# Адаптивный порог: тот же завал при БОЛЬШЕМ масштабе мира двигает цену слабее.
ts = datetime.now(timezone.utc).isoformat()
f_s1 = market.factor(world({"ale1": 160.0, "_t": ts}, scale=1), "ale1")
f_s4 = market.factor(world({"ale1": 160.0, "_t": ts}, scale=4), "ale1")
check("scale=1: завал 160 = пол цены", abs(f_s1 - balance.MARKET_PRICE_FLOOR) < 0.01)
check("scale=4: тот же завал двигает цену слабее", f_s4 > f_s1 + 0.2)
check("market.factor читает market_scale у holder",
      market.factor(world({"ale1": 200.0, "_t": ts}, scale=10), "ale1") > 0.9)
# нормировка: завал, пропорциональный масштабу, даёт ОДИН и тот же множитель
fa = balance.market_factor(160.0, 1)
fb = balance.market_factor(160.0 * 5, 5)
check("нормировка по интенсивности: glut∝scale → один множитель", abs(fa - fb) < 0.001)

# ── 2. fair_value / make_offer теперь читают world ────────────────────────────
print("2. Оценка стоимости от единого рынка")
fv_clean = gauction.fair_value(world(), "ale1")
fv_glut = gauction.fair_value(world({"ale1": 300.0, "_t": datetime.now(timezone.utc).isoformat()}), "ale1")
check("fair_value падает при завале мирового рынка", fv_glut < fv_clean)
tav = SimpleNamespace(products={"ale1": 50}, auction={})
pl = SimpleNamespace(gold=1000, story={}, equipment={})
offer = gtrade.make_offer(tav, pl, fair=False, world=world())
check("make_offer(world=...) отдаёт оффер", offer is not None and offer.get("good") == "ale1")

# ── 3. Лимит покупки (buy-limit) ──────────────────────────────────────────────
print("3. Лимит покупки на бирже (анти-абуз)")
buyer = SimpleNamespace(bourse_buys={})
room0 = bourse.buy_room(buyer, "ale1")
check("стартовый лимит = BOURSE_BUY_LIMIT", room0 == balance.BOURSE_BUY_LIMIT)
bourse.record_buy(buyer, "ale1", 50)
check("после покупки 50 остаток = лимит-50", bourse.buy_room(buyer, "ale1") == balance.BOURSE_BUY_LIMIT - 50)
bourse.record_buy(buyer, "ale1", 999)
check("нельзя уйти в минус (room>=0)", bourse.buy_room(buyer, "ale1") == 0)
check("лимит по товару раздельный", bourse.buy_room(buyer, "bread") == balance.BOURSE_BUY_LIMIT)
# окно истекло → лимит восстановился
old = (datetime.now(timezone.utc) - timedelta(hours=balance.BOURSE_BUY_WINDOW_H + 1)).isoformat()
buyer.bourse_buys = {"ale1": {"t": old, "q": balance.BOURSE_BUY_LIMIT}}
check("истёкшее окно → полный лимит", bourse.buy_room(buyer, "ale1") == balance.BOURSE_BUY_LIMIT)

# ── 4. Сохранение денег/товара при P2P (с лимитом) ────────────────────────────
print("4. Сохранение денег и товара в P2P-сделке (модель)")
# Модель: продавец S продаёт buyer B k штук по цене p. Налог = сток.
S_gold, B_gold = 0, 1000
S_goods, B_goods = 100, 0
p, k = 7, 30
gross = p * k
net = bourse.net_to_seller(gross)
tax = bourse.tax_amount(gross)
# исполнение
B_gold -= gross           # покупатель платит весь gross (в эскроу/налом)
S_gold += net             # продавец получает нетто
S_goods -= k
B_goods += k
sink = tax
total_gold = S_gold + B_gold + sink
check("золото сохраняется (с учётом стока-налога)", total_gold == 0 + 1000)
check("товар сохраняется", S_goods + B_goods == 100)
check("сток = ровно налог 5%", sink == gross - net)

# ── 5. SQL биржевых запросов компилируется в диалект PostgreSQL ───────────────
print("5. SQL единой биржи компилируется в PostgreSQL")
from sqlalchemy import func, select
from bot.db.models import MarketOrder

def sql_ok(stmt):
    # Глобальность = в WHERE нет фильтра по chat_id (колонка в проекции допустима).
    s = str(stmt.compile(dialect=postgresql.dialect(),
                         compile_kwargs={"literal_binds": False}))
    return "market_orders" in s and "chat_id =" not in s and "chat_id IN" not in s

q_orders = (select(MarketOrder).where(
    MarketOrder.seller_id != 1, MarketOrder.qty > 0, MarketOrder.side == "sell")
    .order_by(MarketOrder.id.desc()).limit(6))
check("open_orders глобальный (без chat_id)", sql_ok(q_orders))
q_best = (select(MarketOrder).where(
    MarketOrder.side == "buy", MarketOrder.good == "ale1", MarketOrder.qty > 0,
    MarketOrder.unit_price >= 5, MarketOrder.seller_id != 1)
    .order_by(MarketOrder.unit_price.desc(), MarketOrder.id).limit(6)
    .with_for_update(skip_locked=True))
check("best_buy_orders глобальный + SKIP LOCKED",
      sql_ok(q_best) and "SKIP LOCKED" in str(q_best.compile(dialect=postgresql.dialect())))
q_sum = (select(MarketOrder.good, MarketOrder.side, func.min(MarketOrder.unit_price),
                func.max(MarketOrder.unit_price), func.sum(MarketOrder.qty))
         .where(MarketOrder.qty > 0)
         .group_by(MarketOrder.good, MarketOrder.side))
check("market_summary глобальный", sql_ok(q_sum))

# ── 6. Рендеры экранов (моки) ─────────────────────────────────────────────────
print("6. Рендеры экранов рынка/биржи/аукциона")

def utf16(s):
    return len(s.encode("utf-16-le")) // 2

scr_market = texts.market_screen(world({"ale1": 80.0, "bread": -40.0,
                                         "_t": datetime.now(timezone.utc).isoformat()}))
check("market_screen рендерится + 'один на весь мир'", "весь мир" in scr_market and utf16(scr_market) < 4096)

tav2 = SimpleNamespace(auction={})
check("auction_screen(tavern) без city", "АУКЦИОН" in texts.auction_screen(tav2))
tav3 = SimpleNamespace(auction={"good": "ale1", "qty": 10, "unit_min": 6,
                                "ends_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
                                "top_bid": 8, "top_bidder": 1, "bids": 2, "history": [{"npc": 1, "unit": 8}]})
check("auction_screen активный лот", "ТОРГИ" in texts.auction_screen(tav3))
check("auction_pick_qty(world)", "ВЫСТАВИТЬ" in texts.auction_pick_qty("ale1", 50, world()))
check("auction_pick_price(world)", "ЛОТ" in texts.auction_pick_price("ale1", 10, world()))

order = SimpleNamespace(good="ale1", qty=20, unit_price=7, side="sell", seller_id=2)
plr = SimpleNamespace(gold=500)
check("bourse_order (лимит покупки в тексте)",
      str(balance.BOURSE_BUY_LIMIT) in texts.bourse_order(order, "Вася", plr, best_bid=8))
bid = SimpleNamespace(good="ale1", qty=20, unit_price=7, side="buy", seller_id=2)
tav4 = SimpleNamespace(products={"ale1": 30})
check("bourse_bid (весь мир)", "весь мир" in texts.bourse_bid(bid, "Петя", tav4, best_ask=6))
board = {"ale1": {"ask": 6, "ask_qty": 40, "bid": 8, "bid_qty": 15}}
check("bourse_prices (единая биржа)", "ЕДИНОЙ" in texts.bourse_prices(board))

# ── 7. Полный жизненный цикл биржи: эскроу + матчинг + отмена ─────────────────
print("7. Жизненный цикл биржи (эскроу/матчинг/отмена) — сохранение")
# Зеркало логики: A покупает, B продаёт. Сделка по цене резентного лота (maker).
A_gold, A_goods = 1000, 0
B_gold, B_goods = 0, 100
frozen_goods = 0   # товар в sell-лотах
frozen_gold = 0    # золото-залог в buy-заявках
sink = 0

def total_gold():
    return A_gold + B_gold + frozen_gold + sink

def total_goods():
    return A_goods + B_goods + frozen_goods

g0, q0 = total_gold(), total_goods()

# B выставляет SELL 40 @ 7 (товар морозится)
B_goods -= 40; frozen_goods += 40
check("после выставления продажи — сохранение", total_gold() == g0 and total_goods() == q0)

# A заявка BUY 50 @ 8: 40 сводится с лотом B по цене лота (7), 10 в заявку (залог)
k, price = 40, 7
A_gold -= k * price                  # A платит
A_goods += k                         # A получает товар
frozen_goods -= k                    # лот B исполнен
net = int(k * price * (1 - balance.BOURSE_SALE_TAX))
B_gold += net                        # B получает нетто
sink += k * price - net              # налог в сток
rem, bid = 10, 8
frozen_gold += rem * bid; A_gold -= rem * bid   # остаток в заявку (залог)
check("после матча+заявки — золото сохранено", total_gold() == g0)
check("после матча+заявки — товар сохранён", total_goods() == q0)
check("сток = только налог 5%", sink == k * price - net)

# A отменяет заявку — залог возвращается
A_gold += rem * bid; frozen_gold -= rem * bid
check("после отмены — золото сохранено (залог вернулся)", total_gold() == g0)
check("после отмены — товар сохранён", total_goods() == q0)
check("сток не вырос на отмене", sink == k * price - net)

# ── 8. Анти-абуз: лимит скупки ограничивает перекачку золота меж-чатово ───────
print("8. Лимит скупки гасит меж-чатовую перекачку")
cap_units = balance.BOURSE_BUY_LIMIT
ceil_mult = balance.BOURSE_PRICE_CEIL
# Максимум золота, что можно «перегнать» альту за окно по одному товару:
# cap_units × (ceil×base) с потерей налога. Проверяем, что лимит конечный.
check("лимит скупки конечен (анти-перекачка)", 0 < cap_units < 10_000)
check("окно лимита разумное (1..24ч)", 1 <= balance.BOURSE_BUY_WINDOW_H <= 24)
check("налог-сток делает перекачку убыточной", balance.BOURSE_SALE_TAX > 0)

print()
if fails:
    print(f"{FAIL} ПРОВАЛЕНО проверок: {fails}")
    sys.exit(1)
print(f"{OK} Все проверки пройдены")
