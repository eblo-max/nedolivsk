"""Статический аудит кода: сканеры инвариантов (глубокая проверка 02.07).

Каждый сканер — класс вопросов «а везде ли…». Ловит регрессии архитектурных
правил, из-за которых сегодня трижды падал прод."""

import ast
import os
import re
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test:test")

ROOT = Path(__file__).resolve().parent.parent
WEBAPI = sorted((ROOT / "bot" / "webapi").glob("*.py"))
GAME = sorted((ROOT / "bot" / "game").glob("*.py"))


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_only_market_module_writes_world_market():
    """Урок крашлупа: словари живого мира в world.market роняли decay.
    Писать в .market мира разрешено только bot/game/market.py (+миграции)."""
    offenders = []
    for p in GAME + WEBAPI + [ROOT / "bot" / "notifier.py"]:
        if p.name == "market.py":
            continue
        for i, line in enumerate(_src(p).splitlines(), 1):
            if re.search(r"\bworld\.market\s*=|holder\.market\s*=", line):
                offenders.append(f"{p.name}:{i}")
    assert not offenders, f"запись в world.market вне market.py: {offenders}"


def test_every_api_endpoint_authenticates():
    """Каждый _api_* эндпоинт обязан звать _auth (или это статика/health)."""
    # Осознанные исключения (проверено 02.07):
    # _api_taverns — публичная карта /world вне Telegram-контекста, чужие id не отдаёт;
    # _api_avatar — собственная HMAC-подпись ссылки (initData в <img src> невозможен).
    skip = {"_api_health", "_api_taverns", "_api_avatar"}
    bad = []
    for p in WEBAPI:
        tree = ast.parse(_src(p))
        for node in ast.walk(tree):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and node.name.startswith("_api_")
                    and node.name not in skip):
                body_src = ast.get_source_segment(_src(p), node) or ""
                if ("_auth(" not in body_src
                        and "_verify_init_data" not in body_src):
                    bad.append(f"{p.name}:{node.name}")
    assert not bad, f"эндпоинты без аутентификации: {bad}"


def test_gold_arithmetic_stays_integer():
    """Золото — целое: присваивание .gold с делением обязано оборачиваться
    int()/round()// (иначе дробная мошна и расползание копеек)."""
    bad = []
    for p in GAME + WEBAPI + [ROOT / "bot" / "notifier.py"]:
        for i, line in enumerate(_src(p).splitlines(), 1):
            if re.search(r"\.gold\s*[+\-]?=", line) and "/" in line:
                if not re.search(r"int\(|round\(|//", line):
                    bad.append(f"{p.name}:{i}: {line.strip()[:70]}")
    assert not bad, f"дробное золото: {bad}"


def test_no_naive_utcnow_in_game_code():
    """Время — только offset-aware: naive datetime.now()/utcnow() в игровом
    коде запрещены (сравнение с aware из БД падает TypeError)."""
    bad = []
    pat = re.compile(r"datetime\.now\(\)|datetime\.utcnow\(")
    for p in GAME + WEBAPI + [ROOT / "bot" / "notifier.py"]:
        for i, line in enumerate(_src(p).splitlines(), 1):
            if pat.search(line) and "timezone" not in line:
                bad.append(f"{p.name}:{i}")
    assert not bad, f"naive datetime: {bad}"


def test_notifier_live_world_blocks_are_guarded():
    """Каждый блок живого мира в тике — под своим предохранителем
    (сбой одного не убивает тизеры/рейды: урок трёх крашлупов)."""
    src = _src(ROOT / "bot" / "notifier.py")
    for marker in ("живой мир: слухи", "живой мир: цель недели",
                   "живой мир: NPC-трейдеры", "живой мир: NPC-посты",
                   "тик: market.decay"):
        assert f'logger.exception("{marker}")' in src, f"нет предохранителя: {marker}"


def test_mutating_endpoints_lock_player():
    """Эндпоинты, меняющие золото/инвентарь/экипировку, обязаны брать игрока
    с for_update=True (иначе гонка двух запросов теряет деньги)."""
    MUT = re.compile(r"\bp\.(gold|hp|equipment|inventory|craft_item|build_item|"
                     r"night_run|mill_grain|expeditions)\b\s*[+\-]?=")
    bad = []
    for p in WEBAPI:
        src = _src(p)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("_api_")):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if MUT.search(seg) and "get_player" in seg and "for_update=True" not in seg:
                bad.append(f"{p.name}:{node.name}")
    assert not bad, f"мутация без лока: {bad}"


def test_fgoal_and_npc_use_world_live():
    """Живой мир хранится в world.live (не market) — регресс на переезд."""
    for name in ("fgoal.py", "npc_traders.py", "town_npc.py"):
        src = _src(ROOT / "bot" / "game" / name)
        assert "world.live" in src or "holder.live" in src, f"{name}: не на live"
        assert "world.market =" not in src, f"{name}: пишет в market"


def test_queue_notify_calls_carry_kind():
    """Каждый queue_notify (кроме фото-рассылок) обязан нести kind — иначе весть
    в ленте без иконки/перехода, а срочные (рейд/орда) не доставятся полным
    текстом. Регресс: рейдовые вести текст-бота теряли kind (03.07)."""
    import re
    bad = []
    for p in (ROOT / "bot").rglob("*.py"):
        src = _src(p)
        # находим вызовы queue_notify(...) с балансом скобок
        for m in re.finditer(r"queue_notify\(", src):
            depth, i = 0, m.end() - 1
            while i < len(src):
                depth += (src[i] == "(") - (src[i] == ")")
                if depth == 0:
                    break
                i += 1
            call = src[m.start():i + 1]
            before = src[max(0, m.start() - 5):m.start()]
            if before.endswith("def "):                 # это определение функции
                continue
            arg2 = call.split(",")[1] if call.count(",") >= 1 else ""
            if "chat_id" in arg2:                        # эхо в ОБЩИЙ чат (не личная лента)
                continue
            if "kind=" not in call and "photo=" not in call:
                ln = src[:m.start()].count("\n") + 1
                bad.append(f"{p.name}:{ln}")
    assert not bad, f"queue_notify без kind (и без photo): {bad}"


def test_teaser_window_covers_seen_throttle():
    """Окно активности тизера (feed_ping_targets) должно покрывать троттл
    touch_seen — иначе активный игрок получит тизер, сидя в игре."""
    import re
    from bot.webapi.core import _SEEN_EVERY
    repo_src = _src(ROOT / "bot" / "db" / "repo.py")
    m = re.search(r"active_cut = datetime\.now\(timezone\.utc\) - timedelta\(minutes=(\d+)\)", repo_src)
    assert m, "не найден active_cut в feed_ping_targets"
    window_sec = int(m.group(1)) * 60
    assert window_sec >= _SEEN_EVERY, (window_sec, _SEEN_EVERY)
