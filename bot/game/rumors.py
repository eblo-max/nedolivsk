"""Сарафанное радио (живой мир, фаза 3): слухи о РЕАЛЬНЫХ игроках.

Механики зовут note() на заметных событиях (крупная сделка, ночной куш,
позорная обчистка) — кандидаты копятся в памяти. Нотифаер раз в тик зовёт
flush(): не чаще одного слуха в RUMOR_EVERY_MIN минут слух уходит в летопись
города. Анти-спам: пороги значимости + кулдаун на игрока. Слух — контент,
только пока он редкий."""

import random
import time
from collections import deque

RUMOR_EVERY_MIN = 12        # слух каждые ~12 минут — город болтлив
PLAYER_COOLDOWN_H = 2       # об одном кабатчике — не чаще раза в 2 часа
THRESHOLDS = {"auction": 120, "night": 100, "pickpocket": 25, "trade": 150}

_TEMPLATES = {
    "auction": [
        "🔨 Шепчут у стойки: «{tavern}» подняла {gold} золотых на торгах разом. К большим тратам готовится, не иначе.",
        "🔨 Маклер божится: лот «{tavern}» ушёл с молотка за {gold} монет. Кто-то нынче гуляет.",
    ],
    "trade": [
        "🤝 Купцы меж собой судачат: «{tavern}» выторговала {gold} золотых за одну сделку. Хватка!",
    ],
    "night": [
        "🌙 Гуляет слушок: из «{tavern}» ночью вернулись с котомкой на {gold} золотых. Стража делает вид, что не слышала.",
        "🌙 Тени шепчут: «{tavern}» знает ночные тропы. {gold} монет за одну ходку — завидуй молча.",
    ],
    "pickpocket": [
        "🦝 Смеются в голос: кабатчика из «{tavern}» обчистил зверь-карманник на {gold} монет. Позор-то какой.",
    ],
}

_pending: deque = deque(maxlen=30)      # (ts, player_id, chat_id, text)
_last_by_player: dict[int, float] = {}
_last_flush = 0.0


def note(kind: str, player, gold: int) -> bool:
    """Кандидат в слухи. False — не дотянул до порога/кулдауна/нет чата."""
    if gold < THRESHOLDS.get(kind, 10**9):
        return False
    chat_id = getattr(player, "chat_id", None)
    tavern = getattr(getattr(player, "tavern", None), "name", None)
    if chat_id is None or not tavern:
        return False
    now = time.time()
    if now - _last_by_player.get(player.id, 0.0) < PLAYER_COOLDOWN_H * 3600:
        return False
    _last_by_player[player.id] = now
    text = random.choice(_TEMPLATES[kind]).format(tavern=tavern, gold=int(gold))
    _pending.append((now, int(player.id), int(chat_id), text))
    return True


async def flush(session, repo) -> str | None:
    """Выпустить один слух в летопись города (зовёт нотифаер каждый тик)."""
    global _last_flush
    now = time.time()
    if not _pending or now - _last_flush < RUMOR_EVERY_MIN * 60:
        return None
    _ts, _pid, chat_id, text = _pending.popleft()
    _last_flush = now
    await repo.add_chronicle(session, chat_id, text)
    return text
