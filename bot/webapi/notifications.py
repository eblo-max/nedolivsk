"""Лента уведомлений мини-аппа (раздел «Уведомления»): список/прочитано +
админ-сеятели (все типы вестей, патчноут). Перенесено из bot/webapp.py дословно."""

from datetime import datetime, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth, _chron_ago, _is_admin, touch_seen

# Какие типы склеиваем в ленте («⛏ Бригады вернулись ×3»): массовые повторы
# одного дела; уникальные события (рейд/аукцион/мир) не трогаем.
_GROUP_KINDS = {"exped", "prod", "build", "craft", "hunt", "retail", "mill"}
_GROUP_WINDOW_MIN = 90


def _group_feed(rows: list, now) -> list[dict]:
    """Схлопнуть СОСЕДНИЕ записи одного типа в пределах окна: item.count ≥ 1.
    rows — свежие→старые (как отдаёт feed_list)."""
    out: list[dict] = []
    for r in rows:
        prev = out[-1] if out else None
        same = (prev is not None and r.kind and prev["kind"] == r.kind
                and r.kind in _GROUP_KINDS
                and (prev["_ts"] - r.created_at).total_seconds() <= _GROUP_WINDOW_MIN * 60)
        if same:
            prev["count"] += 1
            prev["read"] = prev["read"] and bool(r.read)
        else:
            out.append({"text": r.text, "read": bool(r.read), "kind": r.kind or "",
                        "count": 1, "_ts": r.created_at,
                        "ago": _chron_ago(r.created_at, now)})
    for it in out:
        it.pop("_ts", None)
    return out


async def _api_notifications(request: web.Request) -> web.Response:
    """Лента уведомлений игрока (раздел «Уведомления») — зеркало ВСЕХ DM + счётчик непрочитанных."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        await touch_seen(s, uid)
        rows = await repo.feed_list(s, uid, 60)
        unread = await repo.feed_unread(s, uid)
        await s.commit()
    items = _group_feed(rows, now)
    return web.json_response({"ok": True, "items": items, "unread": unread},
                             headers={"Cache-Control": "no-store"})


async def _api_notifications_read(request: web.Request) -> web.Response:
    """Отметить все уведомления игрока прочитанными (гасит бейдж)."""
    uid, _body = await _auth(request)
    if uid is None:
        return _body
    async with session_factory() as s:
        await repo.feed_mark_read(s, uid)
        await s.commit()
    return web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})


def _all_notification_samples() -> list[str]:
    """Полный набор ИГРОВЫХ уведомлений с образцовыми данными — для теста ленты (админ).
    Каждый текст в try/except с фолбэком: проблемный объект не валит остальные."""
    from types import SimpleNamespace as NS
    from bot import texts as T

    def t(fn, fallback: str) -> str:
        try:
            r = fn()
            return r if isinstance(r, str) and r.strip() else fallback
        except Exception:   # noqa: BLE001 — образец, фолбэк ок
            return fallback

    bld = NS(emoji="🍺", name="Пивоварня")
    itm = NS(name="Дублёная кольчуга")
    boss = NS(boss_key=next(iter(__import__("bot.game.raid", fromlist=["BOSSES"]).BOSSES), "demon_slime"))
    try:
        from bot.game import season as _se
        seas = _se.SEASONS[_se.season_index(datetime.now(timezone.utc))]
    except Exception:   # noqa: BLE001
        seas = None
    we = NS(emoji="🌧", name="Проливные дожди", blurb="Небо прохудилось — дороги развезло.", good_price=1.0)
    cit = NS(pulse=("ale", -1, "скупает весь эль в округе"), emoji="💰", name="Купец Толстосум")
    hol = NS(emoji="🎉", name="Винокурня-fest", blurb="гуляет весь Недоливск")

    items: list[str] = [
        t(lambda: T.build_ready_notification(bld), "🍺 Пристройка достроена! Загляни в Пристройки."),
        t(lambda: T.craft_ready_notification(itm, 2), "⚒ Вещь готова! Мастер ждёт — забирай."),
        t(lambda: T.expedition_returned(["wood", "ore"]), "🎒 Бригады вернулись! Забирай добычу."),
        t(T.hunter_recovered_notification, "🩹 Охотник оклемался — снова в бой."),
        t(lambda: T.brew_ready_notification(2), "🍺 Эль дображивает — пора разливать."),
        t(lambda: T.brew_aged_notification(2), "🍺 Эль выдержан — особый вкус!"),
        t(lambda: T.meadery_ready_notification("mead"), "🍯 Медовуха поспела."),
        t(T.kitchen_ready_notification, "🍲 Кухня: жаркое готово."),
        t(T.winery_ready_notification, "🍷 Винокурня: вино готово."),
        t(T.malt_ready_notification, "🌾 Солод готов."),
        t(lambda: T.recipe_ready_notification("bread"), "🥖 Партия по рецепту готова."),
        t(lambda: T.auction_settled({"sold": True, "good": "ale1", "qty": 8, "gold": 140,
                                     "unit": 18, "npc": "merchant"}),
          "🔨 Молоток стукнул — лот ушёл! +140 🪙 в мошну."),
        "🔨 Твой лот 8×🍺 Эль заметили на торгах — ставка 22 🪙!",
        "⌛ Лот на бирже истёк — 8×🍺 Эль вернулись в погреб.",
        "⌛ Заявка «куплю» истекла — залог 160 🪙 вернулся.",
        t(lambda: T.bourse_news([("ale1", 20, 18), ("bread", 12, 9)], [("mead", 10, 24)]),
          "📦 Свежие лоты на бирже — загляни на торги."),
        "🚪 Странствующий монах ждёт тебя у стойки — загляни в таверну.",
        t(lambda: T.raid_push_dm(boss), "⚔️ Рейд-босс приближается — открой кабак!"),
        t(T.raid_fight_ping, "⚔️ Битва началась — бей босса!"),
        t(lambda: T.raid_cast_push(boss, ["enrage3"]), "🔥 Босс впал в бешенство — берегись!"),
        t(lambda: T.invasion_push_dm(None), "🪓 Орда орков прёт на Недоливск — в строй!"),
        t(lambda: T.invasion_reward_dm(True, 150, 8, {"wood": 10}, "🗡 Редкий клинок орка"),
          "🏆 Орда разбита! Твоя доля: +150 🪙, +8 репутации, 🪵×10."),
        t(lambda: T.invasion_reward_dm(False, -40, -3), "💀 Орда прорвалась — потери: −40 🪙."),
        t(lambda: T.mill_back_dm(35), "🌾 Телега привезла зерно +35."),
        t(T.bonus_ready_push, "🎁 Бонус дня готов — забери и активируй."),
        t(lambda: T.season_announce(seas) if seas else None, "🍂 Сменился сезон — спрос меняется."),
        t(lambda: T.worldevent_announce(we, None), "🌧 Мировое событие: проливные дожди."),
        t(lambda: T.market_pulse_announce(cit), "📈 Рынок качнуло — цены пошли."),
        "🌍 <b>ВЕСТИ ИЗ НЕДОЛИВСКА</b>\n\n🎪 Ярмарка открылась! Спрос на товары взлетел.",
        t(lambda: T.fair_open_announce(), "🎪 Ярмарка открылась — сбывай, пока берут!"),
        t(lambda: T.holiday_announce(hol), "🎉 В Недоливске праздник!"),
        t(lambda: T.idle_nudge(2), "🍺 Кабак простаивает — загляни, гости заждались."),
        t(lambda: T.onboard_nudge(True), "🏰 Ты завёл двор, но кабак так и не открыл — пора!"),
        "🎟 Зазывала сработал: твой гость дошёл до Недоливска — держи награду!",
    ]
    return [x[:1024] for x in items if x and x.strip()]


async def _api_notifications_seed_all(request: web.Request) -> web.Response:
    """АДМИН-тест: засеять в ленту по образцу ВСЕХ типов игровых уведомлений."""
    uid, _body = await _auth(request)
    if uid is None:
        return _body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    samples = _all_notification_samples()
    # kind по классам сэмплов (тот же порядок, что в _all_notification_samples) —
    # чтобы админ-тест показывал иконки и тап-переходы как у боевых вестей
    kinds = (["build", "craft", "exped", "hunt"] + ["prod"] * 7
             + ["auction"] * 2 + ["bourse"] * 3 + ["story"]
             + ["raid"] * 3 + ["invasion"] * 3 + ["mill", "bonus"]
             + ["world"] * 6 + [""] * 2 + [""])
    async with session_factory() as s:
        for i, txt in enumerate(samples):
            repo.feed_push(s, uid, txt, kind=kinds[i] if i < len(kinds) else "")
        await s.commit()
    return web.json_response({"ok": True, "count": len(samples)},
                             headers={"Cache-Control": "no-store"})


# Патчноут «перенос в мини-апп» — 3 части (≤1024 симв.), для доставки админу в ленту.
_PATCHNOTE_CHUNKS = [
    "📣 ПАТЧНОУТ (3/3) — дорожная карта\n\n"
    "🤝 Гильдии — общий чат, цели, помощь\n"
    "⚔️ Гильдейские войны за регионы на карте\n"
    "🏆 Рейтинги — топ таверн, короны на карте\n"
    "🪓 Вторжение Орды орков в приложении\n"
    "🗺 Карта для всех + действия прямо с карты\n"
    "🌫 Туман войны — открывай мир исследованием\n"
    "🎯 Сезоны и награды\n"
    "🛒 Прямая торговля между игроками\n"
    "✨ Живая карта — облака, точки интереса, события мира",
    "📣 ПАТЧНОУТ (2/3) — что нового\n\n"
    "🗺 Карта мира — общая карта для всех игроков. Таверны отмечены огоньками, "
    "у регионов есть названия, плавный зум на весь экран. Своя таверна выделена.\n\n"
    "🔔 Уведомления — все вести собираются прямо в игре (этот раздел). В чат бот "
    "присылает только короткое напоминание, без спама.\n\n"
    "🔨 Торги — продажи с аукциона, сводки биржи и ярмарка теперь приходят и в общий "
    "чат. Тексты обновили — понятнее и с деталями.\n\n"
    "⚔️ Рейд-босс — бой и призыв прямо в приложении.",
    "📣 ПАТЧНОУТ (1/3) — Недоливск переехал в приложение\n\n"
    "Вся игра теперь в Mini App прямо в Telegram. Управление кнопками, команды не нужны.\n\n"
    "🏰 Уже в приложении:\n"
    "• Таверна — доход, улучшение, сбыт гостям, бонус дня, грамота новосёла\n"
    "• Двор и пристройки — стройка и производство\n"
    "• Персонаж и кузница — статы, снаряжение, ковка, лечение\n"
    "• Вылазки — бригады, охота, ночные ходки\n"
    "• Торг, аукцион и биржа\n"
    "• Рейд-босс\n"
    "• Город — визитёры, летопись, репутация\n"
    "• Зазывала",
]


async def _api_notifications_seed_patchnote(request: web.Request) -> web.Response:
    """АДМИН: прислать себе в ленту патчноут «перенос в мини-апп» (3 части)."""
    uid, _body = await _auth(request)
    if uid is None:
        return _body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    async with session_factory() as s:
        for txt in _PATCHNOTE_CHUNKS:   # порядок: часть 1 окажется сверху ленты
            repo.feed_push(s, uid, txt)
        await s.commit()
    return web.json_response({"ok": True, "count": len(_PATCHNOTE_CHUNKS)},
                             headers={"Cache-Control": "no-store"})


# NPC → аватар (public/npc/N.png). Набор из 20 портретов раскидан по сословиям,
# женщины/иконичные — отдельно; выбор внутри сословия детерминирован по id.


