"""Недельные цели фракций (живой мир, Ф4b): весь город работает на общую цель.

Каждую ISO-неделю фракция объявляет цель; прогресс двигают ВСЕ игроки своими
обычными делами. Выполнили — сутки «городского пира» (+15% к сбыту гостям)
и громкий анонс. Провалили — ничего: цель не кнут, а повод.

Прогресс буферится в памяти (note) и раз в тик пишется в world.market['fgoal']
нотифаером (flush) — как слухи. Пир кэшируется в памяти и гидрируется из
world при старте (переживает деплой)."""

import time
from datetime import datetime, timezone

FEAST_RETAIL_MULT = 1.15      # «город гуляет»: сбыт гостям жирнее
FEAST_HOURS = 24

# Ротация целей по фракциям:
# (фракция, вид, цель, эмблема, короткий титул, задача, анонс в чаты)
# Цели откалиброваны по прод-бухгалтерии 02.07.2026 (~73 активных игрока):
# естественный темп города — сбыт ~60к 🪙/нед, ходки ~14.6к/нед, охота ~сотни
# побед/нед. Цель = ~115-125% натурального: без общего рывка не взять.
GOALS = [
    ("merchants", "gold_trade", 75_000, "⚜️", "Большой торг",
     "Наторгуйте {target} 🪙 всем городом — купцы, гости, аукцион, биржа",
     "⚜️ Купеческая лига объявила Большой торг: наторгуйте {target} 🪙 всем городом — купцы, гости, аукцион, биржа!"),
    ("watch", "hunt", 600, "🛡", "Большая облава",
     "Одолейте {target} тварей на охоте всем городом",
     "🛡 Стража объявила облаву: одолейте {target} тварей на охоте всем городом!"),
    ("thieves", "night", 18_000, "🥷", "Ночь длинных теней",
     "Принесите {target} 🪙 добра из ночных ходок всем городом",
     "🥷 Гильдия скликает тени: принесите из ночных ходок добра на {target} 🪙 всем городом!"),
]

_pending: dict[str, int] = {}     # kind -> накопленный прогресс до flush
_feast_until = 0.0                # epoch: пока не прошло — пир


def week_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def current_goal(now: datetime | None = None) -> dict:
    """Цель этой недели (детерминированная ротация по номеру недели)."""
    now = now or datetime.now(timezone.utc)
    _y, w, _ = now.isocalendar()
    fac, kind, target, emblem, title, task, tpl = GOALS[w % len(GOALS)]
    return {"week": week_key(now), "fac": fac, "kind": kind, "target": target,
            "emblem": emblem, "title": title, "task": task.format(target=target),
            "text": tpl.format(target=target)}


def note(kind: str, amount: int) -> None:
    """Игрок продвинул цель (зовут механики; вид не той недели просто копится зря)."""
    if amount > 0:
        _pending[kind] = _pending.get(kind, 0) + int(amount)


def feast_mult() -> float:
    """Множитель «городского пира» к сбыту гостям (чистая память, без БД)."""
    return FEAST_RETAIL_MULT if time.time() < _feast_until else 1.0


def hydrate(world) -> None:
    """При старте процесса: подтянуть пир из world (переживает деплой)."""
    global _feast_until
    st = (world.market or {}).get("fgoal") or {}
    _feast_until = float(st.get("feast_until") or 0.0)


def flush(world, now: datetime | None = None) -> str | None:
    """Тик нотифаера: слить буфер в world, при выполнении включить пир.
    Возвращает текст анонса выполнения (один раз) либо None."""
    global _feast_until
    now = now or datetime.now(timezone.utc)
    goal = current_goal(now)
    m = dict(world.market or {})
    st = dict(m.get("fgoal") or {})
    if st.get("week") != goal["week"]:            # новая неделя — новая цель
        st = {"week": goal["week"], "done": 0, "rewarded": False,
              "feast_until": st.get("feast_until") or 0.0}
    add = _pending.pop(goal["kind"], 0)
    _pending.clear()                              # чужие виды не копим бесконечно
    if add:
        st["done"] = int(st.get("done", 0)) + add
    announce = None
    if not st.get("rewarded") and st.get("done", 0) >= goal["target"]:
        st["rewarded"] = True
        _feast_until = time.time() + FEAST_HOURS * 3600
        st["feast_until"] = _feast_until
        fac_txt = {"merchants": "Купеческая лига накрывает столы",
                   "watch": "Стража смотрит сквозь пальцы на гулянку",
                   "thieves": "Гильдия проставляется тёмным элем"}[goal["fac"]]
        announce = (f"🎉 <b>ЦЕЛЬ НЕДЕЛИ ВЗЯТА!</b>\n{fac_txt} — "
                    f"город гуляет сутки: <b>сбыт гостям +15%</b>. Наливай!")
    m["fgoal"] = st
    world.market = m
    return announce


def state(world, now: datetime | None = None) -> dict:
    """Снимок для экрана: цель, прогресс, пир (единый источник для UI)."""
    now = now or datetime.now(timezone.utc)
    goal = current_goal(now)
    st = (world.market or {}).get("fgoal") or {}
    done = int(st.get("done", 0)) if st.get("week") == goal["week"] else 0
    return {"fac": goal["fac"], "text": goal["text"],
            "emblem": goal["emblem"], "title": goal["title"], "task": goal["task"],
            "done": min(done, goal["target"]), "target": goal["target"],
            "pct": min(100, round(done * 100 / goal["target"])),
            "feast": feast_mult() > 1.0}
