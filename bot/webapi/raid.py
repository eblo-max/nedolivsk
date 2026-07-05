"""Рейд-босс в мини-аппе: состояние/запись/удары/сводки + админ-призыв с анонсом
в чаты. Жизненный цикл крутит нотифаер; боевая логика — bot/game/raid (та же, что
в чате). Перенесено из bot/webapp.py дословно (move-only)."""

from datetime import datetime, timedelta, timezone

from aiohttp import web

from bot.db import repo
from bot.db.base import session_factory
from bot.webapi.core import _auth, _is_admin, get_bot

RAID_REPORT_SEC = 20 * 60   # сколько сводка победы/ухода висит на экране рейда


def _secs_until(dt, now) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((dt - now).total_seconds()))


def _raid_loot_dto(boss_key: str) -> list[dict]:
    """Витрина добычи: что с туши может пасть и с каким шансом (для экрана рейда)."""
    from bot.game import raid as rd, balance as bal
    spec = rd.BOSSES.get(boss_key)
    if spec is None:
        return []
    total = sum(w for _, w, _ in spec.loot) or 1
    out = []
    for tag, w, payload in spec.loot:
        pct = round(100 * w / total, 1)
        if tag == "gear":
            out.append({"icon": "🛡", "label": "Эксклюзивная снаряга", "pct": pct, "gear": True})
        elif tag == "gold":
            lo, hi = payload
            out.append({"icon": "🪙", "label": f"{lo}–{hi} золота", "pct": pct})
        elif tag == "ingot":
            lo, hi = payload
            out.append({"icon": bal.RESOURCE_EMOJI.get("ingot", "📦"),
                        "label": f"Слитки ×{lo}–{hi}", "pct": pct})
        else:  # res:<name>
            res, lo, hi = payload
            out.append({"icon": bal.RESOURCE_EMOJI.get(res, "📦"),
                        "label": f"{bal.RESOURCE_NAMES.get(res, res)} ×{lo}–{hi}", "pct": pct})
    return out


def _raid_roster(boss, uid: int = 0) -> list[dict]:
    """Бойцы: имя/урон/удары, флаг mine (pid наружу не отдаём — приватность)."""
    rows = [{"name": r.get("name", ""), "dmg": int(r.get("dmg", 0)),
             "hits": int(r.get("hits", 0)), "mine": bool(uid) and pid == str(uid)}
            for pid, r in (boss.contributions or {}).items()]
    rows.sort(key=lambda x: (-x["dmg"], x["name"]))
    return rows[:8]


def _raid_dto(boss, uid: int = 0) -> dict | None:
    """Полное состояние живого босса для экрана рейда: фаза сбора (отсчёт/строй/
    добыча) либо битвы (HP/фаза/активные касты/мой кулдаун)."""
    from bot.game import raid as rd
    spec = rd.BOSSES.get(boss.boss_key)
    if spec is None:
        return None
    now = datetime.now(timezone.utc)
    base = {
        "id": boss.id, "key": boss.boss_key, "name": spec.name, "emoji": spec.emoji,
        "sprite": spec.sprite or "", "blurb": spec.blurb, "armor": spec.armor,
        "status": boss.status, "n": rd.registered_count(boss),
        "me_registered": rd.is_registered(boss, uid) if uid else False,
        "roster": _raid_roster(boss, uid),
        "gear_pct": rd.gear_drop_pct(boss.boss_key), "loot": _raid_loot_dto(boss.boss_key),
    }
    if boss.status == "gathering":
        base["gather_left"] = _secs_until(boss.gather_until, now)
        base["preview_hp"] = rd.boss_start_hp(boss)   # масштаб боя под текущую явку
    elif boss.status == "active":
        adds = rd.adds_hp(boss)
        adds_max = max(1, int(boss.max_hp * rd.SUMMON_HP_PCT))
        base.update({
            "hp": max(0, boss.hp), "max_hp": boss.max_hp,
            "hp_pct": round(100 * max(0, boss.hp) / boss.max_hp) if boss.max_hp else 0,
            "phase": rd.phase(boss), "ends_left": _secs_until(boss.ends_at, now),
            "stun_left": rd.stun_left(boss, now), "ward_left": rd.ward_left(boss, now),
            "curse_left": rd.curse_left(boss, now),
            "adds_hp": adds, "adds_pct": round(100 * adds / adds_max) if adds else 0,
        })
        if uid:
            base["my_cd"] = rd.cooldown_left(boss, uid, now)
            base["my_stunned"] = rd.stunned(boss, uid, now)
    return base


def _raid_summary(boss, uid: int = 0) -> dict | None:
    """Компактная сводка для снапшота Таверны: показать кнопку «⚔️ РЕЙД-БОСС»."""
    from bot.game import raid as rd
    spec = rd.BOSSES.get(boss.boss_key)
    if spec is None:
        return None
    now = datetime.now(timezone.utc)
    out = {"id": boss.id, "name": spec.name, "emoji": spec.emoji, "sprite": spec.sprite or "",
           "status": boss.status, "me_registered": rd.is_registered(boss, uid) if uid else False,
           "n": rd.registered_count(boss)}
    if boss.status == "gathering":
        out["left"] = _secs_until(boss.gather_until, now)
    elif boss.status == "active":
        out["hp_pct"] = round(100 * max(0, boss.hp) / boss.max_hp) if boss.max_hp else 0
        out["phase"] = rd.phase(boss)
        out["left"] = _secs_until(boss.ends_at, now)
    return out


def _raid_report_dto(boss, uid: int = 0) -> dict | None:
    """Пост-боевая сводка (победа/уход) для тех, кто не добил сам. Доля золота
    ДЕТЕРМИНИРОВАНА (пул÷бойцы) — её показываем точно; победителя/трофей не трогаем
    (их рандом уже применён и ушёл пушем-уведомлением)."""
    from bot.game import raid as rd
    spec = rd.BOSSES.get(boss.boss_key)
    if spec is None:
        return None
    now = datetime.now(timezone.utc)
    # окно показа: до ends_at + RAID_REPORT_SEC (убитого досрочно ends_at в будущем →
    # видно сразу; ушедшего/добитого под конец — ещё RAID_REPORT_SEC после ends_at)
    if boss.ends_at:
        ea = boss.ends_at if boss.ends_at.tzinfo else boss.ends_at.replace(tzinfo=timezone.utc)
        if (now - ea).total_seconds() > RAID_REPORT_SEC:
            return None
    won = boss.status == "dead"
    my_gold = 0
    if won and uid:
        try:
            my_gold = int(rd.settle(boss)["gold"].get(uid, 0))   # gold-сплит детерминирован
        except Exception:   # noqa: BLE001 — сводка не должна ронять экран
            my_gold = 0
    return {
        "id": boss.id, "key": boss.boss_key, "name": spec.name, "emoji": spec.emoji,
        "sprite": spec.sprite or "", "status": boss.status, "report": True, "won": won,
        "top": _raid_roster(boss, uid), "my_gold": my_gold,
        "i_fought": bool(uid) and int((boss.contributions or {}).get(str(uid), {}).get("dmg", 0)) > 0,
    }


async def _raid_start_if_due(s, boss, now):
    """Сбор вышел → перевести в БОЙ ПРЯМО СЕЙЧАС (не ждать нотифаер ≤60с — из-за
    него босс «появлялся» через 20-30с после 0:00). Под локом + повторная проверка
    (анти-гонка: первый запрос переводит, остальные видят уже active). Чат-анонсы
    догонит нотифаер на своём тике. Возвращает свежий boss (active/expired)."""
    if boss is None or boss.status != "gathering" or not boss.gather_until:
        return boss
    gu = boss.gather_until if boss.gather_until.tzinfo else boss.gather_until.replace(tzinfo=timezone.utc)
    if now < gu:
        return boss
    from bot.game import raid as rd
    from bot import texts as _t
    locked = await repo.get_raid(s, boss.id, lock=True)
    if locked is None or locked.status != "gathering":
        return locked or boss            # другой запрос/нотифаер уже перевёл
    lgu = locked.gather_until if locked.gather_until.tzinfo else locked.gather_until.replace(tzinfo=timezone.utc)
    if now < lgu:
        return locked
    if rd.registered_count(locked) > 0:
        locked.max_hp = locked.hp = rd.boss_start_hp(locked)
        locked.status = "active"
        locked.ends_at = rd.fight_until(now)
        for pid in list((locked.contributions or {}).keys()):
            repo.queue_notify(s, int(pid), _t.raid_fight_ping(), kind="raid")
    else:
        locked.status = "expired"        # никто не пришёл — ушёл
    await s.commit()
    return locked


async def _api_raid(request: web.Request) -> web.Response:
    """Состояние рейд-босса для мини-аппа: живой босс либо свежая сводка боя."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        boss = await repo.get_active_raid(s)
        boss = await _raid_start_if_due(s, boss, now)    # сбор вышел → бой/уход сразу
        if boss is not None and boss.status in ("gathering", "active"):
            dto = _raid_dto(boss, uid)
            # фляга: что уже выпито на этот бой + что есть в погребе (эль/вино/сбитень)
            from bot.game import balance as bal, production as prodm, raid as rd
            p = await repo.get_player(s, uid)
            prods = (p.tavern.products if p and p.tavern else None) or {}
            me = (boss.contributions or {}).get(str(uid)) or {}
            dto["flask"] = {
                "drunk": me.get("flask"),
                # все фляги из погреба; метка — РЕЙД-эффект (rd.flask_label), т.к. в
                # рейде hp/уворот идут в урон — «+45❤» тут было бы показ≠действие.
                "options": [{"key": k, "name": prodm.GOODS[k].name,
                             "emoji": prodm.GOODS[k].emoji,
                             "label": rd.flask_label(k),
                             "qty": int(prods.get(k, 0))}
                            for k in bal.FLASK_EFFECTS
                            if k in prodm.GOODS and int(prods.get(k, 0)) > 0],
            }
        elif boss is not None and boss.status in ("dead", "expired"):
            dto = _raid_report_dto(boss, uid)
        else:
            latest = await repo.latest_raid(s)
            dto = (_raid_report_dto(latest, uid)
                   if latest and latest.status in ("dead", "expired") else None)
    return web.json_response({"ok": True, "raid": dto, "admin": _is_admin(uid),
                              "bosses": _raid_boss_list()},
                             headers={"Cache-Control": "no-store"})


def _raid_boss_list() -> list[dict]:
    """Список боссов для админ-призыва (key/имя/эмодзи/спрайт)."""
    from bot.game import raid as rd
    return [{"key": k, "name": b.name, "emoji": b.emoji, "sprite": b.sprite or ""}
            for k, b in rd.BOSSES.items()]


async def _api_raid_join(request: web.Request) -> web.Response:
    """Записаться в рейд (фаза сбора). Калька cb_raid_join: лочим босса, register,
    лог, коммит. Возвращает свежее состояние."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import raid as rd
    async with session_factory() as s:
        player = await repo.get_player(s, uid)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        boss = await repo.get_active_raid(s, lock=True)
        if boss is None or boss.status != "gathering":
            return web.json_response({"ok": False, "error": "closed"})
        if not rd.register(boss, player):
            return web.json_response({"ok": True, "already": True, "raid": _raid_dto(boss, uid)},
                                     headers={"Cache-Control": "no-store"})
        repo.add_log(s, "player", player.id, "⚔️ записался в рейд (мини-апп)")
        await s.commit()
        dto = _raid_dto(boss, uid)
    return web.json_response({"ok": True, "raid": dto}, headers={"Cache-Control": "no-store"})


async def _api_raid_hit(request: web.Request) -> web.Response:
    """Удар по боссу (фаза битвы). Калька cb_raid_hit 1:1: порядок локов босс→игрок,
    проверки записи/кулдауна/оглушения, raid.resolve_hit, при смерти — settle +
    раздача золота + _drop_apply победителю + пуши, коммит ДО любой косметики."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    from bot.game import raid as rd, economy
    from bot.handlers.raid import _drop_apply
    from bot import texts
    async with session_factory() as s:
        boss = await repo.get_active_raid(s, lock=True)
        if boss is None or boss.status == "dead":
            return web.json_response({"ok": False, "error": "gone"})
        if boss.status == "gathering":
            return web.json_response({"ok": False, "error": "not_started"})
        if boss.status != "active":
            return web.json_response({"ok": False, "error": "gone"})
        player = await repo.get_player(s, uid, for_update=True)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        if not rd.is_registered(boss, player.id):
            return web.json_response({"ok": False, "error": "not_registered"})

        now = datetime.now(timezone.utc)
        left = rd.cooldown_left(boss, player.id, now)
        if left > 0:                                  # рано бить — мягкий ответ (не ошибка)
            return web.json_response(
                {"ok": True, "hit": False, "wait": left,
                 "stunned": rd.stunned(boss, player.id, now), "raid": _raid_dto(boss, uid)},
                headers={"Cache-Control": "no-store"})

        # Фляга на рейд: первый удар списывает порции из погреба, дальше — весь бой.
        from bot.game import combat as cb
        cons = dict(boss.contributions or {})
        me = dict(cons.get(str(uid)) or {})
        fl = me.get("flask")
        if fl is None:
            keys = [str(k) for k in ((body or {}).get("flask") or [])]
            _, fl, _ = cb.flask_apply(player, keys, {}, 0) if keys else (0, [], [])
            me["flask"] = fl
            cons[str(uid)] = me
            boss.contributions = cons
        res = rd.resolve_hit(boss, player, now, flask_keys=fl)  # урон + фляга + проклятье/щит/толща/миньоны
        repo.add_log(s, "player", player.id, f"⚔️ рейд: −{res['dmg']} HP боссу (мини-апп)")
        second_wind = rd.maybe_second_wind(boss, now)  # хил+рык на 30% HP (один раз)

        if not rd.is_dead(boss):
            push = texts.raid_cast_push(boss, res.get("casts", []))   # «громкие» касты — бойцам
            if push:
                for pid in (boss.contributions or {}):
                    if int(pid) != player.id:
                        repo.queue_notify(s, int(pid), push, kind="raid")
            await s.commit()                            # урон в БД ДО ответа
            toast = ("🐲 ВТОРОЕ ДЫХАНИЕ! Босс воспрял и взревел — все оглушены!"
                     if second_wind else texts.raid_hit_toast(res, boss.hp, boss.max_hp))
            return web.json_response(
                {"ok": True, "hit": True, "toast": toast, "second_wind": second_wind,
                 "crit": bool(res.get("crit")), "casts": res.get("casts", []),
                 "dmg": int(res.get("dmg", 0)), "adds_dmg": int(res.get("adds_dmg", 0)),
                 "adds_hit": bool(res.get("adds_dmg")), "raid": _raid_dto(boss, uid)},
                headers={"Cache-Control": "no-store"})

        # ── Босс повержен: раздача (как в чате) ──
        boss.status = "dead"
        plan = rd.settle(boss)
        for pid in sorted(plan["gold"]):                # единый порядок локов (по возрастанию id)
            pp = await repo.get_player(s, pid, for_update=True)
            if pp is not None:
                pp.gold += plan["gold"][pid]
                economy.record(pp, "raid", int(plan["gold"][pid]))
                repo.queue_notify(s, pid,
                                  f"⚔️ Босс повержен! Твоя доля добычи: +{plan['gold'][pid]} 🪙",
                                  kind="raid")
        drop_line, winner_name = "", None
        if plan["winner"] is not None:
            winner = await repo.get_player(s, plan["winner"], for_update=True)
            if winner is not None:
                winner_name = winner.first_name or str(winner.id)
                got = _drop_apply(winner, plan["drop"])
                if got:
                    rarity = rd.RARITY.get((plan["drop"] or {}).get("rarity"), "")
                    drop_line = f"{rarity} — {got}" if rarity else got
                    repo.queue_notify(s, winner.id, f"🎁 С босса тебе выпал {rarity} трофей: {got}", kind="raid")
        top_full = sorted(((pid, r.get("name", pid), int(r.get("dmg", 0)))
                           for pid, r in (boss.contributions or {}).items()
                           if r.get("dmg", 0) > 0), key=lambda x: -x[2])
        # Флаг + данные победы нотифаеру: правь чатовые анонсы на экран «ПОВЕРЖЕН»
        # (килл случился в мини-аппе, не в чате — чат сам не узнает).
        boss.state = dict(boss.state or {}, mini_kill=True,
                          win_name=winner_name or "", win_drop=drop_line or "")
        await s.commit()                                # награды зафиксированы
        rd.set_active(None)                             # убрать кнопку «Рейд-босс» из меню
        spec = rd.BOSSES[boss.boss_key]
        victory = {
            "name": spec.name, "emoji": spec.emoji, "sprite": spec.sprite or "",
            "top": [{"name": n, "dmg": d, "mine": pid == str(player.id)}
                    for pid, n, d in top_full[:8]],
            "my_gold": int(plan["gold"].get(player.id, 0)),
            "winner": winner_name, "drop": drop_line, "i_killed": True,
        }
    return web.json_response({"ok": True, "hit": True, "dead": True, "victory": victory},
                             headers={"Cache-Control": "no-store"})


async def _api_raid_seed(request: web.Request) -> web.Response:
    """ТЕСТ (только админ): призвать демона и сразу запустить битву (записать админа,
    выставить HP), чтобы вживую погонять экран рейда, не дожидаясь сбора/нотифаера."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from bot.game import raid as rd
    key = (body.get("key") or "demon_slime")
    if key not in rd.BOSSES:
        return web.json_response({"ok": False, "error": "no_boss"})
    async with session_factory() as s:
        player = await repo.get_player(s, uid, for_update=True)
        if player is None or not player.tavern:
            return web.json_response({"ok": False, "error": "no_tavern"})
        boss = await repo.get_active_raid(s, lock=True)
        if boss is None:                                # призвать нового
            boss = repo.create_raid(s, key, rd.gather_until())
            await s.flush()
        rd.register(boss, player)                       # вписать админа
        if boss.status == "gathering":                  # сразу в бой
            boss.max_hp = boss.hp = rd.boss_start_hp(boss)
            boss.status = "active"
            boss.ends_at = rd.fight_until()
        rd.set_active(boss.id)
        repo.add_log(s, "player", player.id, "🧪 тест: призван рейд-босс (мини-апп)")
        await s.commit()
        dto = _raid_dto(boss, uid)
    return web.json_response({"ok": True, "raid": dto, "admin": True},
                             headers={"Cache-Control": "no-store"})


async def _api_raid_summon(request: web.Request) -> web.Response:
    """НАСТОЯЩИЙ призыв рейд-босса из мини-аппа (только админ) — как чат-админка:
    фаза СБОРА 20 мин, анонс во ВСЕ чаты (через бота), пуш в ЛС активным игрокам
    (через очередь — доставит нотифаер). Не как seed: тут реальный сбор и рассылка."""
    uid, body = await _auth(request)
    if uid is None:
        return body
    if not _is_admin(uid):
        return web.json_response({"ok": False, "error": "forbidden"}, status=403)
    from sqlalchemy import select as _select
    from bot.db.models import Player as _Player
    from bot.game import raid as rd
    from bot import texts as _t
    from bot.handlers.raid import send_raid_announce
    from bot.keyboards.inline import raid_gather_kb
    from bot.sender import deliver
    key = (body.get("key") or "demon_slime")
    if key not in rd.BOSSES:
        return web.json_response({"ok": False, "error": "no_boss"})
    async with session_factory() as s:
        if await repo.get_active_raid(s) is not None:
            return web.json_response({"ok": False, "error": "busy"})   # уже есть активный
        boss = repo.create_raid(s, key, rd.gather_until())
        await s.flush()                                   # нужен boss.id для кнопок
        repo.add_log(s, "player", uid, f"⚔️ призвал рейд-босса {key} (мини-апп)")
        # 1) анонс во все чаты (видео/текст) — если бот доступен
        text = _t.raid_gather_screen(boss)
        msgs: dict[str, int] = {}
        _bot = get_bot()
        if _bot is not None:
            for cid in await repo.all_chat_ids(s):
                sent = await deliver(lambda c=cid: send_raid_announce(
                    _bot, c, boss, text, raid_gather_kb(boss.id)), what=f"raid→{cid}")
                if sent is not None:
                    msgs[str(cid)] = sent.message_id
            boss.messages = msgs
        # 2) пуш в ЛС активным за 7 дней (очередь — доставит нотифаер)
        cut = datetime.now(timezone.utc) - timedelta(days=7)
        pids = (await s.execute(
            _select(_Player.id).where(_Player.last_seen_at >= cut))).scalars().all()
        for pid in pids:
            repo.queue_notify(s, pid, _t.raid_push_dm(boss), kind="raid")
        rd.set_active(boss.id)                             # кнопка «Рейд-босс» сразу
        await s.commit()
        dto = _raid_dto(boss, uid)
    return web.json_response(
        {"ok": True, "raid": dto, "admin": True, "chats": len(msgs), "pushed": len(pids)},
        headers={"Cache-Control": "no-store"})

