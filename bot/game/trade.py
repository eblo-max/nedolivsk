"""Торг с заезжими купцами (гибрид A+D) — с характерами.

Купец — личность: архетип задаёт жадность, нужду, достаток, предпочтение
товара и ГОЛОС. Он рассуждает вслух и принимает взвешенные решения под своё
положение: принимает, контрит (лоуболит), уступает при дожиме или уходит.

Сдерживание цен — рыночное: справедливая цена-якорь (fv), потолок наценки,
бюджет покупателя, ограниченная партия, случайный приход (без монополии).
"""

import random
from dataclasses import dataclass

from bot.game import balance, market, production as prod, story_state


@dataclass(frozen=True)
class Archetype:
    id: str
    emoji: str
    names: tuple
    greed: tuple          # диапазон жадности (0..1)
    need: tuple           # диапазон нужды
    wealth_mult: tuple    # множитель бюджета на fv*qty
    qty_mult: float       # множитель объёма партии
    pref: str             # 'premium' | 'cheap' | 'bulk' | 'any'
    intro: tuple          # как представляется (рассуждает о товаре)
    accept: tuple         # берёт по выгодной/рыночной
    accept_high: tuple    # берёт, но дорого
    counter: tuple        # контр-предложение ({p} -> цена)
    walk: tuple           # уходит
    concede: tuple        # уступает при дожиме ({p})
    hold: tuple           # упирается при дожиме ({p})


ARCHES = [
    Archetype(
        "miser", "🤑", ("Барыга Кривой Грош", "Скупец Сквалыгин", "Жмот Полушкин"),
        greed=(0.7, 1.0), need=(0.1, 0.25), wealth_mult=(0.9, 1.3), qty_mult=1.0,
        pref="cheap",
        intro=("щурится и пересчитывает медяки на ладони",
               "морщится, будто товар уже тухлый"),
        accept=("«Ну… так и быть, заверни»", "«По рукам, но это грабёж»"),
        accept_high=("«Дерёшь втридорога, кровопийца… ладно»",),
        counter=("«Побойся бога! Больше {p} не дам, и не проси»",
                 "«{p} — моё последнее слово, жмот ты эдакий»"),
        walk=("«Грабёж средь бела дня! Поищу подешевле»",
              "«За такое?! Тьфу. Бывай»"),
        concede=("«Эх… ну {p}, чёрт с тобой, последний раз»",),
        hold=("«Сказал {p} — значит {p}. Бери или вали»",),
    ),
    Archetype(
        "connoisseur", "🎩", ("Господин Винокуров", "Барон фон Похмель", "Ценитель Сладкоежкин"),
        greed=(0.1, 0.35), need=(0.3, 0.5), wealth_mult=(1.4, 2.0), qty_mult=0.8,
        pref="premium",
        intro=("поводит носом, оценивая букет, и брезгливо щурится",
               "вертит кружку на свету, знаток с виду"),
        accept=("«Достойно. Беру не глядя»", "«Вот это вещь. Заверни»"),
        accept_high=("«Дороговато, но качество того стоит. Идёт»",),
        counter=("«За такое — {p}, и ни монетой больше. Я знаю толк»",),
        walk=("«Это пойло не стоит таких денег. Прощай»",
              "«Уважаю себя, чтоб переплачивать. Бывай»"),
        concede=("«Хм… {p}? За хороший товар — извольте»",),
        hold=("«{p}, и это щедро. Решайтесь»",),
    ),
    Archetype(
        "desperate", "😰", ("Бедолага Сухоглот", "Странник Жаждущий", "Погорелец Нищов"),
        greed=(0.1, 0.3), need=(0.45, 0.65), wealth_mult=(0.7, 1.1), qty_mult=0.7,
        pref="any",
        intro=("озирается, сглатывает, товар нужен ему позарез",
               "трясущимися руками шарит по карманам"),
        accept=("«Слава богам! Давай скорей»", "«Беру-беру, спасибо, родимый!»"),
        accept_high=("«Дорого, да деваться некуда… держи»",),
        counter=("«Не могу больше {p}, в кошеле пусто, войди в положение»",),
        walk=("«Нету у меня столько… эх»", "«Не по карману. Пойду я»"),
        concede=("«Наскребу {p}, последнее отдаю»",),
        hold=("«{p} — всё, что есть, хоть режь»",),
    ),
    Archetype(
        "bulk", "📦", ("Обозный Возилов", "Оптовик Мешков", "Купчина Складов"),
        greed=(0.4, 0.7), need=(0.2, 0.35), wealth_mult=(1.6, 2.4), qty_mult=1.7,
        pref="bulk",
        intro=("кивает на пустой обоз — берёт помногу, но по своей цене",
               "прикидывает, сколько влезет в телегу"),
        accept=("«Гружу всё. Объём — моё дело»", "«Беру оптом, по рукам»"),
        accept_high=("«Дорого за партию, но возьму. Один раз»",),
        counter=("«Оптом — по {p} за штуку, не иначе. Считай выгоду»",),
        walk=("«За такие деньги наберу в другом месте»",),
        concede=("«Ладно, {p}, но грузим всё подчистую»",),
        hold=("«{p} за штуку — и по рукам, или ищу другого»",),
    ),
    Archetype(
        "reveler", "🍺", ("Гуляка Бражников", "Кутила Весёлый", "Пьянчуга при Золоте"),
        greed=(0.0, 0.2), need=(0.4, 0.6), wealth_mult=(1.1, 1.6), qty_mult=1.0,
        pref="any",
        intro=("уже навеселе, щедр и сорит деньгами",
               "хохочет и хлопает по столу — гулять так гулять"),
        accept=("«Гуляем! Наливай, забираю!»", "«Деньги — тлен! Беру!»"),
        accept_high=("«Дорого? Да плевать, я гуляю! Держи!»",),
        counter=("«Ну хоть {p}, по-дружески, а?»",),
        walk=("«Не, ну это уж совсем… пойду к другим гулять»",),
        concede=("«А, была не была — {p}!»",),
        hold=("«{p}, и пьём мировую!»",),
    ),
    Archetype(
        "shrewd", "🧐", ("Делец Хитров", "Купец Расчётов", "Маклер Тёртый"),
        greed=(0.4, 0.6), need=(0.25, 0.4), wealth_mult=(1.2, 1.8), qty_mult=1.1,
        pref="any",
        intro=("знает рынок назубок и чует, когда его пытаются надуть",
               "спокоен, считает в уме каждый грош выгоды"),
        accept=("«Цена честная. По рукам»", "«Разумно. Беру»"),
        accept_high=("«На грани, но сделка того стоит. Идёт»",),
        counter=("«Знаю я рынок: красная цена — {p}. Ну так что?»",),
        walk=("«Меня не надуешь. Найду выгоднее»",
              "«Завышаешь. Я лучше подожду»"),
        concede=("«{p}? Разумный компромисс. Идёт»",),
        hold=("«{p} — справедливо. Дальше торга не будет»",),
    ),
]
ARCH = {a.id: a for a in ARCHES}


def has_sellable(tavern) -> bool:
    prods = tavern.products or {}
    return any(v > 0 and k in prod.GOODS for k, v in prods.items())


def _pick_good(prods: dict, pref: str, rng: random.Random) -> str:
    if pref == "premium":
        return max(prods, key=lambda k: prod.GOODS[k].price)
    if pref == "cheap":
        return min(prods, key=lambda k: prod.GOODS[k].price)
    if pref == "bulk":
        return max(prods, key=lambda k: prods[k])
    return rng.choice(list(prods))


def make_offer(tavern, player, fair: bool, rng: random.Random | None = None,
               city=None) -> dict | None:
    rng = rng or random
    prods = {k: v for k, v in (tavern.products or {}).items()
             if v > 0 and k in prod.GOODS}
    if not prods:
        return None
    arch = rng.choice(ARCHES)
    good = _pick_good(prods, arch.pref, rng)

    mkt = market.factor(city, good)   # завал рынка чата давит оптовую цену
    fv = (prod.GOODS[good].price
          * (balance.TRADE_FAIR_FV_MULT if fair else 1.0) * mkt)
    greed = rng.uniform(*arch.greed)
    need = rng.uniform(*arch.need)
    rel = min(0.3, max(0, story_state.faction(player, "merchants")) / 300)

    max_unit = fv * (1 + need + rel) * (1 - greed * 0.3)
    max_unit = max(fv * balance.TRADE_MIN_UNDER,
                   min(fv * balance.TRADE_MAX_OVER, max_unit))

    qty_base = int(rng.randint(balance.TRADE_QTY_MIN, balance.TRADE_QTY_MAX)
                   * arch.qty_mult)
    qty = max(1, min(prods[good], qty_base))
    wealth = int(fv * qty * rng.uniform(*arch.wealth_mult))

    name = rng.choice(arch.names)
    prices = [max(1, int(round(fv * t))) for t in balance.TRADE_PRICE_TIERS]
    return {
        "good": good, "qty": qty, "arch": arch.id, "emoji": arch.emoji,
        "name": name, "intro": rng.choice(arch.intro),
        "fv": round(fv, 2), "max_unit": round(max_unit, 2), "wealth": wealth,
        "greed": round(greed, 3), "prices": prices, "mkt": round(mkt, 3),
    }


def _qty_affordable(offer: dict, unit: int) -> int:
    by_budget = offer["wealth"] // unit if unit > 0 else 0
    return max(0, min(offer["qty"], by_budget))


def evaluate(offer: dict, unit: int) -> tuple[str, int]:
    """Реакция: ('accept'|'counter'|'walk', цена). Контр — лоуболл от потолка."""
    mx = offer["max_unit"]
    if unit <= mx:
        return "accept", unit
    if unit <= mx * balance.TRADE_COUNTER_MARGIN:
        # контрит чуть ниже своего потолка — оставляет себе место для торга
        counter = max(1, int(round(mx * (1 - offer["greed"] * 0.08))))
        return "counter", counter
    return "walk", 0


def push(offer: dict, rng: random.Random | None = None) -> tuple[str, int]:
    """Дожим контр-цены: ('concede'|'hold'|'walk', цена). По характеру."""
    rng = rng or random
    greed = offer["greed"]
    ceiling = int(round(offer["max_unit"]))
    current = int(offer.get("counter", ceiling))
    if greed < 0.55 and ceiling > current:
        return "concede", ceiling           # уступает до истинного потолка
    if greed >= 0.75 and rng.random() < 0.5:
        return "walk", 0                     # жадный обижается и уходит
    return "hold", current                   # стоит на своём


def reaction(offer: dict, kind: str, price: int | None = None) -> str:
    """Реплика купца под исход (kind: accept|accept_high|counter|walk|concede|hold)."""
    arch = ARCH[offer["arch"]]
    pool = getattr(arch, kind, None) or arch.accept
    phrase = random.choice(pool)
    return phrase.format(p=price) if price is not None else phrase
