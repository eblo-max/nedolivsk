"""Админ-команды. Работают только для ADMIN_ID из настроек."""

from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot import announce, texts
from bot.config import settings
from bot.db import repo
from bot.db.models import Player, Tavern
from bot.game import balance, economy, invasion, wonder as wmod
from bot.game import world as wld
from bot.keyboards.inline import invasion_announce_kb
from bot.sender import deliver

router = Router()


def _is_admin(message: Message) -> bool:
    return settings.admin_id != 0 and message.from_user.id == settings.admin_id


@router.message(Command("orc"))
async def cmd_orc(message: Message, command: CommandObject, session: AsyncSession) -> None:
    """Запустить ивент «Орда орков». /orc — обычный; /orc fast — быстрый тест-режим."""
    if not _is_admin(message):
        return
    if await repo.get_active_invasion(session) is not None:
        await message.answer("Орда уже идёт — дождись итога текущего ивента.")
        return
    args = (command.args or "").lower().split()
    fast = "fast" in args
    seed_army = "army" in args             # /orc fast army — болванка-армия для отладки
    # /orc ... winsN — тест эскалации: посчитать escal как при N победах мира
    # (только для ЭТОГО нашествия, постоянный счётчик world.orc_wins не трогаем).
    wins_override = next((int(a[4:]) for a in args
                          if a.startswith("wins") and a[4:].isdigit()), None)
    now = datetime.now(timezone.utc)
    total = await repo.world_might_sum(session)
    world = await repo.get_or_create_world(session)
    threshold = invasion.horde_threshold(total)
    g_until, r_at = invasion.schedule(now, fast=fast)
    inv = repo.create_invasion(session, sprite=invasion.SPRITE, threshold=threshold,
                               gather_until=g_until, resolve_at=r_at)
    if seed_army:
        inv.registered = invasion.dummy_roster()   # 16 бойцов с человеч. никами
    world.invasion_next_at = None          # активна — авто не спавнит поверх
    wins_for_escal = (wins_override if wins_override is not None
                      else getattr(world, "orc_wins", 0))
    # Твердыня (готовое чудо) РЕАЛЬНО ослабляет Орду через escal (он влияет на
    # simulate; threshold — лишь эталон сложности). Снимок при спавне (показ=действие).
    inv.escal = invasion.escalation(wins_for_escal) * wmod.invasion_escal_mult(world)
    await session.flush()                  # нужен inv.id для кнопок
    invasion.set_gathering(inv.id)         # меню таверны сразу покажет «в строй» у ВСЕХ
    gsec = round((g_until - now).total_seconds())
    repo.add_log(session, "admin", message.from_user.id,
                 f"🪓 запущена Орда орков ({'fast ' if fast else ''}порог {threshold}, "
                 f"сбор {gsec}с)")

    if invasion.TEST_MODE:                  # тест: без анонсов в чаты/лички — только админу
        from bot.webapp import base_url
        from bot.keyboards.inline import invasion_map_dm_kb
        b = base_url()
        kb = invasion_map_dm_kb(b + "/world") if b else None
        timing = (f"⚡ быстрый режим: сбор {invasion.FAST_GATHER_SECONDS}с, "
                  f"бой по темпу (~{invasion.FAST_MARCH_SECONDS}с марш + раунды)" if fast
                  else f"сбор {invasion.GATHER_MINUTES} мин, бой по реальному темпу "
                       f"(полоска HP тает раунд за раундом, "
                       f"{invasion.MIN_BATTLE_SECONDS}–{invasion.MAX_BATTLE_SECONDS}с)")
        army = "\n🤖 Болванка-армия: 16 бойцов (🛡4 🗡6 ⚔️4 🔭2) — город уже силён." if seed_army else ""
        await message.answer(
            f"🪓 <b>Орда запущена в ТЕСТ-режиме</b> (без анонсов в чаты/лички).\n"
            f"Порог {threshold} (мощь города {total}). Эскалация ×{inv.escal:.2f} "
            f"(побед мира {getattr(world, 'orc_wins', 0)}). {timing}.{army}\n"
            "Открой карту — записывайся и тестируй:",
            reply_markup=kb)
        return

    from bot.handlers.invasion import send_invasion_announce
    caption = texts.invasion_gather_screen(inv)
    chat_ids = await repo.all_chat_ids(session)
    msgs: dict[str, int] = {}
    for cid in chat_ids:
        sent = await deliver(lambda c=cid: send_invasion_announce(
            message.bot, c, caption, invasion_announce_kb(inv.id)), what=f"orc→{cid}")
        if sent is not None:
            msgs[str(cid)] = sent.message_id
    inv.messages = msgs
    cut = now - timedelta(days=7)
    pids = [r[0] for r in (await session.execute(
        select(Player.id).where(Player.last_seen_at >= cut))).all()]
    for uid in pids:
        repo.queue_notify(session, uid, texts.invasion_push_dm(inv), kind="invasion")
    army = ("\n🤖 Подсажена болванка-армия: 16 бойцов с никами — город уже силён, "
            "живые добьют." if seed_army else "")
    await message.answer(
        f"🪓 Орда орков запущена! Порог орды: <b>{threshold}</b> "
        f"(мощь города {total}). Эскалация: <b>×{inv.escal:.2f}</b> "
        f"(побед мира {getattr(world, 'orc_wins', 0)}). "
        f"Сбор {invasion.GATHER_MINUTES} мин. "
        f"В чаты: {len(msgs)}/{len(chat_ids)}. Пуш в личку: {len(pids)}.{army}")


@router.message(Command("reset"))
async def cmd_reset(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    if not _is_admin(message):
        return  # молча игнорируем чужаков
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Так: /reset <telegram_id>")
        return

    target_id = int(command.args.strip())
    player = await session.get(Player, target_id)
    if player is None:
        await message.answer(f"Игрок {target_id} не найден. Некого сносить.")
        return

    await session.execute(delete(Tavern).where(Tavern.player_id == target_id))
    await repo.delete_player_orders(session, target_id)
    await session.execute(delete(Player).where(Player.id == target_id))
    await message.answer(
        f"🔥 Готово. Игрок {target_id} стёрт подчистую — таверна, золото, "
        "слот на карте. Пусть жмёт /start и начинает с нуля."
    )


@router.message(Command("app"))
async def cmd_app(message: Message) -> None:
    """Открыть мини-апп Недоливска. Доступно всем — только в личке (web_app)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from bot.webapp import base_url
    if message.chat.type != "private":
        await message.answer("🏰 Мини-апп открывается в личке — напиши мне в ЛС и жми «🏰 Открыть в приложении».")
        return
    b = base_url()
    if not b:
        await message.answer("Мини-апп временно недоступен — приложение ещё разворачивается.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏰 Открыть Недоливск", web_app=WebAppInfo(url=b + "/app"))],
    ])
    await message.answer(
        "🏰 <b>Недоливск</b> — таверна теперь в приложении!\n"
        "Внутри: твоя таверна, стройка, персонаж с кузницей и вылазки на тракт.",
        reply_markup=kb,
    )


@router.message(Command("fair"))
async def cmd_fair(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message):
        return
    world = await repo.get_or_create_world(session)
    wld.open_fair(world)
    await session.flush()  # зафиксировать состояние мира до рассылки
    chat_ids = await repo.all_chat_ids(session)
    await announce.broadcast_fair(message.bot, "open", chat_ids, world)
    await message.answer(
        f"🎪 Ярмарка открыта вручную на {balance.FAIR_DURATION_HOURS} ч. "
        f"Спрос ×{balance.FAIR_DEMAND_MULT:g}. Анонс ушёл в чаты: {len(chat_ids)}."
    )


@router.message(Command("wonder"))
async def cmd_wonder(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    """Заложить общую стройку «Чудо города» (одна живая на весь мир). Фаза 1:
    без чат-анонса — вклад через /api/wonder; мини-апп и карта появятся в Фазе 3."""
    if not _is_admin(message):
        return
    args = (command.args or "").lower().split()
    if "wipe" in args:                       # ЧИСТЫЙ СТАРТ перед запуском всем: погасить ВСЕ живые
        from sqlalchemy import select as _select   # чуда + снять глоб-баффы + заложить свежее по
        from bot.db.models import Wonder           # актуальной калибровке. Устраняет тест-остатки.
        live_ws = list((await session.execute(
            _select(Wonder).where(Wonder.status.in_(("building", "sealing")))
            .with_for_update())).scalars().all())
        for w in live_ws:
            w.status = "expired"             # не building/sealing → нотифаер не трогает
        world = await repo.get_or_create_world(session)
        lv = dict(world.live or {})
        had = list(lv.get("wonders_done") or [])
        lv["wonders_done"] = []              # снять глоб-баффы готовых чудес (заработаются заново)
        world.live = lv
        wdef = wmod.get(wmod.FIRST_WONDER)
        active = await repo.active_player_count(session)
        target = wmod.phase_target(wdef.phases[0].base_target, active)
        repo.create_wonder(session, key=wmod.FIRST_WONDER, target=target)
        # опц. «me»: снести ЛИЧНЫЕ тест-награды вызвавшего админа (титулы/фасады/рецепты
        # из story['artel'] + зодары) — чтобы стартовать с чистого листа, как все.
        me_line = ""
        if "me" in args:
            me = await repo.get_player(session, message.from_user.id, for_update=True)
            if me is not None:
                a = (me.story or {}).get("artel") or {}
                nt = len(a.get("titles") or [])
                nf = len(a.get("facades") or []) or (1 if a.get("facade") else 0)
                nr = len(a.get("recipes") or [])
                z0 = int(getattr(me, "zodar", 0) or 0)
                st = dict(me.story or {}); st.pop("artel", None); me.story = st
                me.zodar = 0
                me_line = (f" Личные тест-награды снесены: титулов {nt}, фасадов {nf}, "
                           f"рецептов {nr}, зодаров {z0}→0.")
        repo.add_log(session, "admin", message.from_user.id,
                     f"🏛 /wonder wipe — погашено {len(live_ws)}, сняты буфы {had}, свежее (цель {target}){me_line}")
        await message.answer(
            f"🏛 <b>Вайп выполнен.</b> Погашено активных чудес: <b>{len(live_ws)}</b>, "
            f"снят глоб-бафф: {had or '—'}. Заложено свежее «{wdef.emoji} {wdef.name}»: "
            f"фаза 1 «{wdef.phases[0].title}», цель <b>{target}</b> очков (активных {active}).{me_line} "
            f"Готово к открытию всем.")
        return
    if "reset" in args or "stop" in args:    # закрыть текущую стройку (тихо), чтобы начать заново
        w = await repo.get_active_wonder(session, lock=True)
        if w is None:
            await message.answer("🏛 Активной стройки нет — закладывай: <b>/wonder</b>")
            return
        w.status = "expired"                 # не building/sealing → нотифаер не трогает, буф не жмёт
        repo.add_log(session, "admin", message.from_user.id, f"🏛 /wonder reset — «{w.key}» закрыта")
        await message.answer("🏛 Стройка закрыта. Заложить новую: <b>/wonder</b>")
        return
    if "retarget" in args:                   # пересчитать цель ТЕКУЩЕЙ фазы вживую (тюнинг темпа):
        w = await repo.get_active_wonder(session, lock=True)  # /wonder retarget [N] — N явно ИЛИ
        if w is None or w.status != "building":               # по обновлённой base×активные. Прогресс цел.
            await message.answer("🏛 Нет активной строящейся стройки.")
            return
        wdef = wmod.get(w.key)
        active = await repo.active_player_count(session)
        ph = int(w.phase)
        nums = [int(x) for x in args if x.isdigit()]
        if nums:
            new_t = max(int(w.progress) + 1, nums[0])
        else:
            base = (wdef.phases[ph - 1].base_target
                    if wdef and 0 < ph <= len(wdef.phases) else int(w.target))
            new_t = max(int(w.progress) + 1, wmod.phase_target(base, active))
        old_t = int(w.target)
        w.target = new_t
        w.updated_at = datetime.now(timezone.utc)
        repo.add_log(session, "admin", message.from_user.id,
                     f"🏛 /wonder retarget — фаза {ph}: {old_t}→{new_t}")
        await message.answer(
            f"🏛 Цель фазы {ph} пересчитана: <b>{old_t} → {new_t}</b> очков "
            f"(активных {active}). Прогресс {w.progress} сохранён — фаза стала длиннее.")
        return
    if "fill" in args:                       # ТЕСТ: форс-прогресс, чтобы увидеть крепость
        w = await repo.get_active_wonder(session, lock=True)
        if w is None:
            await message.answer("🏛 Сперва заложи чудо: /wonder")
            return
        wdef = wmod.get(w.key)
        p = await repo.get_player(session, message.from_user.id, for_update=True)
        active = await repo.active_player_count(session)
        pts = max(1, round(0.4 * int(w.target)))      # +40% текущей фазы за вызов
        res = wmod.apply_contribution(
            w, str(p.id), (p.first_name or "Зодчий") if p else "Зодчий", pts, pts, active)
        w.updated_at = datetime.now(timezone.utc)
        if p is not None:
            p.zodar = int(getattr(p, "zodar", 0) or 0) + int(res["award"])
        repo.add_log(session, "admin", message.from_user.id, f"🏛 /wonder fill +{pts}")
        state = ("🏁 ЗАВЕРШЕНО (settle тихо на след. тике)" if res["wonder_done"]
                 else f"фаза {w.phase}/{len(wdef.phases) if wdef else '?'}")
        await message.answer(
            f"🏛 fill: +{pts} → <b>{w.progress}/{w.target}</b> ({state}), "
            f"+{res['award']} ⚒ (баланс {p.zodar if p else 0} ⚒). Обнови мини-апп.")
        return
    if await repo.get_active_wonder(session) is not None:
        await message.answer("🏛 Стройка уже идёт — сперва доведите текущее чудо.")
        return
    key = wmod.FIRST_WONDER
    wdef = wmod.get(key)
    if wdef is None:
        await message.answer("Нет такого чуда в реестре.")
        return
    active = await repo.active_player_count(session)
    target = wmod.phase_target(wdef.phases[0].base_target, active)
    repo.create_wonder(session, key=key, target=target)
    repo.add_log(session, "admin", message.from_user.id,
                 f"🏛 заложено чудо «{wdef.name}» (цель фазы 1 {target}, активных {active})")
    await message.answer(
        f"🏛 Заложено чудо «{wdef.emoji} {wdef.name}». Фаза 1 «{wdef.phases[0].title}», "
        f"цель <b>{target}</b> очков (активных {active}). Вклад — через /api/wonder. "
        f"Эффект по готовности: {wdef.bonus}.")


@router.message(Command("econ"))
async def cmd_econ(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    """Бухгалтерия экономики (faucet/sink). /econ — сводка; /econ reset — обнулить окно."""
    if not _is_admin(message):
        return
    world = await repo.get_or_create_world(session)
    if (command.args or "").strip().lower() == "reset":
        await session.execute(update(Player).values(econ={}))
        world.econ_since = datetime.now(timezone.utc)
        await message.answer("📊 Бухгалтерия обнулена — окно замера начато заново.")
        return

    rows = (await session.execute(select(Player.econ))).scalars().all()
    agg: dict[str, int] = {}
    for e in rows:
        for k, v in (e or {}).items():
            agg[k] = agg.get(k, 0) + int(v)

    since = world.econ_since
    days = None
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        days = max((datetime.now(timezone.utc) - since).total_seconds() / 86400, 1e-6)

    def per(v: int) -> str:
        return f" ({v / days:+.0f}/дн)" if days else ""

    def block(cats: dict[str, str]) -> tuple[list[str], int]:
        lines, total = [], 0
        for cat in sorted(cats, key=lambda c: -abs(agg.get(c, 0))):
            v = agg.get(cat, 0)
            if v == 0:
                continue
            total += v
            lines.append(f"  {cats[cat]} — <b>{v:+}</b>{per(v)}")
        return lines, total

    fa, fa_tot = block(economy.FAUCETS)
    si, si_tot = block(economy.SINKS)
    net = fa_tot + si_tot
    win = f"{days:.1f} дн" if days else "?"
    out = [f"📊 <b>ЭКОНОМИКА</b> — окно {win}", ""]
    out += ["🟢 <b>КРАНЫ</b> (приток):", *(fa or ["  —"]),
            f"  <i>Итого крана: {fa_tot:+}{per(fa_tot)}</i>", ""]
    out += ["🔴 <b>СТОКИ</b> (отток):", *(si or ["  —"]),
            f"  <i>Итого стока: {si_tot:+}{per(si_tot)}</i>", ""]
    out += [f"⚖️ <b>Чистый приток: {net:+}</b>{per(net)}",
            "<i>+ = золото копится в мире (инфляция), − = осушается.</i>"]
    await message.answer("\n".join(out))
