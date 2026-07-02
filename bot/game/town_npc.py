"""NPC-жители чата (живой мир, фаза 5): пишут в общие чаты по расписанию.

Стражник Косой — вечерняя сводка (21:15 МСК): реальное состояние мира.
Перекуп Сизый — пятничное объявление (12:05 МСК): его НАСТОЯЩИЕ ордера с биржи.
Тексты — шаблоны + живые цифры; не чаще раза в день на NPC (метка в world)."""

import random
from datetime import datetime


def _day(now: datetime) -> str:
    return now.date().isoformat()


def _once_per_day(world, key: str, now: datetime) -> bool:
    """True — сегодня ещё не постил (и пометить, что постим)."""
    m = dict(world.market or {})
    posts = dict(m.get("npc_posts") or {})
    if posts.get(key) == _day(now):
        return False
    posts[key] = _day(now)
    m["npc_posts"] = posts
    world.market = m
    return True


def watchman_post(orders_cnt: int, raid_alive: bool, event_name: str | None,
                  rumor: str | None, rng: random.Random | None = None) -> str:
    """Вечерняя сводка стражника — из реальных фактов дня."""
    rng = rng or random
    lines = ["🛡 <b>Стражник Косой, вечерний обход:</b>"]
    if raid_alive:
        lines.append("— Тварь у стен ещё жива. Кто при оружии — в строй, остальным сидеть по кабакам.")
    if event_name:
        lines.append(f"— В городе {event_name}. Приказано не вмешиваться.")
    lines.append(f"— На бирже к ночи {orders_cnt} живых лотов. Торгуйте, пока честные.")
    if rumor:
        lines.append(f"— {rumor}")
    lines.append(rng.choice([
        "Ночью не шляться без нужды. А кто шляется — делиться.",
        "Кто пьян — тому по чарке за счёт заведения... шучу. По домам!",
        "Замечу кого у чужого погреба — сначала палка, потом вопросы.",
    ]))
    return "\n".join(lines)


def dealer_post(orders: list[dict]) -> str | None:
    """Пятничный клич перекупа — по его РЕАЛЬНЫМ buy-ордерам ({good_name, qty, unit})."""
    if not orders:
        return None
    rows = "\n".join(f"— {o['good_name']}: до {o['qty']} шт. по {o['unit']} 🪙"
                     for o in orders[:3])
    return ("💰 <b>Перекуп Сизый объявляет скупку:</b>\n" + rows +
            "\n«Несите на биржу, беру без разговоров. Кто первый — тому и монета.»")
