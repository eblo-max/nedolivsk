"""Вылазка «Телега за зерном» к мельнице на карте.

Таймер + кулдаун: снарядил телегу → ~30 мин в пути (анимация телеги на карте) →
вернулась с зерном; следующая вылазка — через COOLDOWN с момента отправки.
Состояние держим на игроке: mill_run_at (отправка) + mill_grain (улов, ждёт сбора).

Машина состояний (выводится из run_at/grain/now):
  idle      — телега дома, кулдаун прошёл → можно снаряжать;
  transit   — телега в пути (grain зарезервирован, ещё не доехала);
  ready     — телега вернулась, зерно ждёт сбора;
  cooldown  — улов забран, мельница «отдыхает» до конца кулдауна.
Чистый модуль: без БД/IO (начисление зерна — снаружи, через inventory.add).
"""

from datetime import datetime, timedelta, timezone

TRIP_SECONDS = 30 * 60          # ~30 мин в пути (туда-обратно)
COOLDOWN_SECONDS = 3 * 3600     # 3 ч между вылазками (с момента отправки)

# Улов зерна: база + от уровня таверны + от удачи (снаряга), со случайным «помолом».
GRAIN_BASE = 22
GRAIN_PER_LEVEL = 2
GRAIN_PER_LUCK = 0.6
MISHAP_CHANCE = 0.10            # «тряхнуло на ухабе» — часть просыпал
MISHAP_MULT = 0.6
RICH_CHANCE = 0.12             # «богатый помол» — телега под завязку
RICH_MULT = 1.5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def yield_grain(player, rng) -> tuple[int, str]:
    """Сколько зерна привезёт телега + флейвор-нота («богатый помол»/«тряхнуло»/'')."""
    from bot.game import combat
    tav = getattr(player, "tavern", None)
    lvl = max(1, int(getattr(tav, "level", 1) or 1))
    luck = int(combat.player_stats(player).get("luck", 0))
    base = GRAIN_BASE + lvl * GRAIN_PER_LEVEL + luck * GRAIN_PER_LUCK
    r = rng.random()
    if r < MISHAP_CHANCE:
        return max(1, round(base * MISHAP_MULT)), "mishap"
    if r < MISHAP_CHANCE + RICH_CHANCE:
        return max(1, round(base * RICH_MULT)), "rich"
    return max(1, round(base)), ""


def base_grain(player) -> int:
    """Ожидаемый улов без случайности — для сравнения «богатый/тряхнуло» при сборе."""
    from bot.game import combat
    tav = getattr(player, "tavern", None)
    lvl = max(1, int(getattr(tav, "level", 1) or 1))
    luck = int(combat.player_stats(player).get("luck", 0))
    return max(1, round(GRAIN_BASE + lvl * GRAIN_PER_LEVEL + luck * GRAIN_PER_LUCK))


def state(player, now: datetime | None = None) -> dict:
    """Текущее состояние вылазки + тайминги (секунды) для UI/анимации."""
    now = now or _now()
    run_at = _aware(getattr(player, "mill_run_at", None))
    grain = int(getattr(player, "mill_grain", 0) or 0)
    if grain > 0 and run_at is not None:
        done_at = run_at + timedelta(seconds=TRIP_SECONDS)
        if now < done_at:                      # ещё едет
            return {"state": "transit", "grain": grain,
                    "elapsed_secs": round((now - run_at).total_seconds()),
                    "trip_secs": TRIP_SECONDS,
                    "back_in": round((done_at - now).total_seconds())}
        return {"state": "ready", "grain": grain,   # вернулась — забирай
                "elapsed_secs": round((now - run_at).total_seconds()),
                "trip_secs": TRIP_SECONDS}
    if run_at is not None:                      # grain == 0 → собрано/пусто
        ready_at = run_at + timedelta(seconds=COOLDOWN_SECONDS)
        if now < ready_at:
            return {"state": "cooldown", "ready_in": round((ready_at - now).total_seconds())}
    return {"state": "idle"}


def can_send(player, now: datetime | None = None) -> bool:
    return state(player, now)["state"] == "idle"


def send(player, rng, now: datetime | None = None) -> bool:
    """Снарядить телегу: фиксируем отправку и зарезервированный улов. False — нельзя."""
    if not can_send(player, now):
        return False
    grain, _note = yield_grain(player, rng)
    player.mill_run_at = now or _now()
    player.mill_grain = grain
    return True


def collect(player, now: datetime | None = None) -> int:
    """Забрать привезённое зерно (если телега вернулась). Возвращает кол-во (0 — нечего).
    Начисление в инвентарь — у вызывающего; тут лишь снимаем резерв (mill_grain=0)."""
    st = state(player, now)
    if st["state"] != "ready":
        return 0
    grain = int(player.mill_grain or 0)
    player.mill_grain = 0                       # run_at оставляем — он держит кулдаун
    return grain
