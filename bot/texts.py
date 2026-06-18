"""Все игровые тексты в одном месте. Тон — жёсткий трактирный."""

import random
from html import escape

from bot.db.models import Player, Tavern
from bot.game import balance, inventory, logic
from bot.game import world as wld
from bot.game.balance import RESOURCE_EMOJI, RESOURCE_NAMES

# Единая подпись-ссылка на канал новостей/обновлений (добавляется к ключевым экранам).
CHANNEL_FOOTER = (
    "\n\n📣 Новости и обновы по игре — "
    "<a href=\"https://t.me/nedolivsk\">@nedolivsk</a>"
)

WELCOME = (
    "🍺 <b>НЕДОЛИВСК. ДОБРО ПОЖАЛОВАТЬ, ЧЁ УЖ.</b>\n"
    "<blockquote>Сраный городишко, где эль разбавляют мочой, посуду моют раз "
    "в год по обещанию, а за лишний вопрос живо пересчитают зубы.</blockquote>\n\n"
    "Тут ты заводишь свой кабак и, если по дороге не сдохнешь, тащишь эту "
    "вонючую наливайку в богатейший двор округи: гонишь работяг за добром, "
    "варишь пойло, спаиваешь сброд и гребёшь золото лопатой.\n\n"
    "И не думай, что это тупая дрочильня по таймеру. Тут <b>живой город</b>, "
    "блядь: жители со своими мерзкими рожами, заговоры, фракции, пьяные драмы — "
    "и каждый твой косяк город запомнит да при случае припомнит.\n\n"
    "Захочешь развернуться по-настоящему — волоки бота в общий чат. У всей "
    "вашей бухой компашки заведётся целый Недоливск, один на всех.\n\n"
    "📣 Новости, обновы и весь движ — в канале "
    "<a href=\"https://t.me/nedolivsk\">@nedolivsk</a>. Подпишись, чтоб не проморгать.\n\n"
    "Ну хорош пялиться. Наливай да за дело."
)

LIVING_CITY = (
    "🏰 <b>ЖИВОЙ НЕДОЛИВСК</b>\n"
    "Заруби на пропитом носу: это не дрочильня по таймеру. Городишко живёт "
    "своей блядской жизнью, и всем насрать, удобно тебе или нет.\n\n"
    "🍻 <b>Гости с историями.</b> Только присел барыш считать — на порог уже "
    "припёрся какой-нибудь мудак: пьяный рыцарь канючит в долг, стражник тянет "
    "на лапу, бард лезет петь похабень, ведьма впаривает гадание, картёжник "
    "разводит на кости. И каждый раз решаешь ты — а прилетит и доброе, и "
    "хуёвое.\n\n"
    "🧠 <b>Город всё помнит, падла.</b> Послал барда — сложит про твой кабак "
    "такую песню, что сгоришь со стыда. Сдружился с рыцарем — притащит знатных "
    "бухарей с золотом. У каждой рожи своя память и своя многоходовка, что "
    "раскручиваешь до жирного куша.\n\n"
    "🏛 <b>Пять сил рвут город на куски.</b> Стража, воры, купцы, корона, "
    "церковь. Твои дела решают, кто наверху. Задружишь — жирные плюшки (воры не "
    "обнесут, купцы накинут к выручке, мышцы дешевле). Кинешь — получишь нож в "
    "спину, сиречь вендетту.\n\n"
    "🎪 <b>И расхлёбывают все.</b> Поднимется кто-то один — в городе пиздец на "
    "ВСЕХ: воровской беспредел снимает долю с кассы, купеческий бум всем "
    "задирает спрос, корона трясёт поборами, церковь гонит в пост. Плюс общий "
    "настрой города — кошелёк его чует.\n\n"
    "Короче: не один ты в песочнице. Ты житель живого склочного бухого городка."
)

ADD_TO_CHAT = (
    "👥 <b>НЕДОЛИВСК НА ВСЮ ПЬЯНУЮ КОМПАШКУ</b>\n"
    "Весь сок — в общем чате. Затащи бота в свою беседу, и заведётся "
    "<b>общий город, один на всех</b>. В одну харю бухать — последнее дело.\n\n"
    "Чё наваришь:\n"
    "🏘 <b>Один Недоливск на чат</b> — вы всей толпой качаете одни фракции и "
    "общую судьбу. Один насрал — расхлёбывают все.\n"
    "🎪 <b>События валятся в чат</b> — ярмарки, заговоры, беспредел, бум.\n"
    "📜 <b>Общая летопись</b> — кто кого сдал, кто поднялся, кто спился под лавкой.\n"
    "🏆 <b>Рейтинг беседы</b> — у кого кабак жирнее, а у кого помойка.\n"
    "🍺 <b>Играешь прямо в чате</b> словом «гг» — своя панель, чужая лапа не тронет.\n\n"
    "Как затащить:\n"
    "1. Добавь бота в группу.\n"
    "2. Дай права читать сообщения — иначе «гг» он хрен услышит.\n"
    "3. Любой пишет «гг» — и понеслась пьянка.\n\n"
    "Чем больше народу — тем злее и веселее город."
)

COMMANDS_SCREEN = (
    "⌨️ <b>ШПАРГАЛКА ДЛЯ ЗАБЫВЧИВЫХ</b>\n"
    "В личке всё на кнопках — тут даже ты не заблудишься. В чате командуешь "
    "словом <b>«гг»</b>:\n\n"
    "🍺 <b>Кабак и дела</b>\n"
    "• <code>гг</code> / <code>гг таверна</code> — твой кабак\n"
    "• <code>гг склад</code> — запасы · <code>гг перс</code> — персонаж · "
    "<code>гг кузница</code> — снаряга · <code>гг охота</code> — зверьё\n"
    "• <code>гг бонус</code> — ежедневный опохмел (баф на 4 ч)\n\n"
    "💰 <b>Торговля</b>\n"
    "• <code>гг рынок</code> — живые цены · <code>гг аукцион</code> — выставить лот\n\n"
    "🏰 <b>Живой город</b>\n"
    "• <code>гг город</code> — расклад фракций · <code>гг хроника</code> — летопись\n"
    "• <code>гг репутация</code> — кто как к тебе относится + плюшки\n\n"
    "🗺 <b>Мир</b>\n"
    "• <code>гг карта</code> — карта · <code>гг топ</code> — рейтинг\n"
    "• <code>гг правила</code> — как играть · <code>гг помощь</code> — этот хаб\n\n"
    "В личке всё на кнопках; слэш-меню: <code>/start /bonus /market /auction "
    "/hunt /top /map /help</code>.\n"
    "<i>Чужую панель не лапай — жмёт только хозяин.</i>"
) + CHANNEL_FOOTER

ASK_TAVERN_NAME = (
    "📜 Как обзовёшь свою забегаловку?\n\n"
    "Пиши название (от 2 до 40 знаков). Думай головой — "
    "с этой вывеской тебе жить и спиваться."
)

NAME_TOO_LONG = "Ты бы ещё поэму накатал. От 2 до 40 знаков — и без соплей."

ASK_REGION = (
    "🗺 Где вкопаешь первый столб, <b>{name}</b>?\n\n"
    "❄️ <b>Северная глушь</b> — леса по самое горло (🪵 +50%), "
    "зато хмель дохнет на морозе (🌿 −25%)\n\n"
    "🌾 <b>Зелёные долины</b> — зерна хоть лопатой греби (🌾 +50%), "
    "но лес давно вырубили под пашню (🪵 −25%)\n\n"
    "🏜 <b>Красные пустоши</b> — дикий хмель крепче кулака (🌿 +50%), "
    "а зерно горит на солнце (🌾 −25%)\n\n"
    "Выбирай. Потом не скули."
)

CREATED = (
    "🍻 Ну всё, <b>{name}</b> открыта. Регион — <b>{region}</b>.\n\n"
    "В мошне 100 🪙 — не пропей в первый же вечер.\n"
    "Гони работников за ресурсами и поднимай этот сарай с колен."
)

GROUP_HINT = (
    "🍺 «Недоливск» наливает только в личке.\n"
    "Стучись к боту напрямую — здесь только языками чешут."
)

GROUP_NEED_TAVERN = (
    "🍺 А кабака-то у тебя ещё нет, мил человек.\n"
    "Завести можно только в личке — назвать да место выбрать. "
    "Жми кнопку, а как обзаведёшься — рули прямо отсюда: «гг таверна»."
)

GROUP_HELP = (
    "🍺 <b>Недоливск — командуй прямо в чате:</b>\n"
    "• <b>гг</b> или <b>гг таверна</b> — твой кабак\n"
    "• <b>гг перс</b> — персонаж и кузница\n"
    "• <b>гг склад</b> — запасы\n"
    "• <b>гг кузница</b> — заказать снаряжение\n"
    "• <b>гг карта</b> — карта мира\n"
    "• <b>гг топ</b> — доска почёта\n"
    "• <b>гг хроника</b> — летопись города\n"
    "• <b>гг город</b> — расклад сил фракций\n"
    "• <b>гг репутация</b> — как тебя знают горожане\n"
    "• <b>гг правила</b> — как вообще играть\n"
    "Кнопки чужой панели жать нельзя — только хозяин."
) + CHANNEL_FOOTER

RULES = (
    "🍺 <b>НЕДОЛИВСК — КАК ПОДНЯТЬ КАБАК</b>\n"
    "<blockquote>Из вонючей наливайки — в богатейший кабак. Чем больше оборот, "
    "тем выше в «гг топ» (рейтинг по ВВП).</blockquote>\n\n"

    "<b>━ ОСНОВНОЙ ЦИКЛ ━</b>\n\n"

    "<b>⛏ 1. Бригады — добыча</b>\n"
    "«Отправить бригады» — работяги идут за деревом, зерном, хмелём, мёдом, "
    "ягодой, рудой, солью, рыбой, молоком. Платишь вперёд, через время "
    "«Забираешь» добычу. Чем выше уровень — больше бригад (вторая уже "
    "на ур.3).\n\n"

    "<b>🏗 2. Пристройки — переработка</b>\n"
    "Сырьё надо переработать. Одно сырьё кормит разные цепочки:\n"
    "<code>зерно → солод / мука</code> — Мельница\n"
    "<code>руда → слиток</code> — Горн\n"
    "<code>солод + хмель → эль</code> — Пивоварня\n"
    "<code>мёд → медовуха / сбитень</code> — Медоварня\n"
    "<code>мука → хлеб / пирог</code> — Пекарня\n"
    "<code>дичь/рыба + соль → солонина / копчёности</code> — Коптильня\n"
    "<code>молоко + соль → сыр / масло</code> — Сыроварня\n"
    "<code>дичь + припасы → жаркое</code> — Кухня\n"
    "<code>ягоды → вино</code> — Винодельня\n"
    "<i>Часть пристроек открывается с репутацией.</i>\n\n"

    "<b>🍺 3. Погреб и выдержка</b>\n"
    "Запускаешь партию → ждёшь (придёт уведомление) → разливаешь в погреб. Эль "
    "можно поставить на <u>выдержку</u>: шанс поднять ярус <code>★→★★★</code> "
    "(дороже), но может и скиснуть. Погреб не резиновый — излишек киснет, "
    "сбывай вовремя.\n\n"

    "<b>━ КУДА СБЫВАТЬ (4 канала) ━</b>\n\n"

    "<b>💰 4. Касса — гостям</b>\n"
    "«Собрать доход»: <u>пассив</u> капает сам, а гости говорят, сколько хотят "
    "выкупить — ты решаешь «налить» или «придержать». Состоятельные берут "
    "дорогое, пьянь — дешёвое, голодные — еду. Больше вместимость и "
    "репутация — выше выручка.\n\n"

    "<b>🤝 5. Купец</b>\n"
    "Иногда на сбор дохода заходит заезжий купец за партией. Ставишь цену — он "
    "соглашается, торгуется или уходит (по нраву). Дороже розницы, но цену "
    "надо угадать.\n\n"

    "<b>🔨 6. Аукцион NPC</b>\n"
    "Выставляешь лот — горожане сами перебивают ставки по таймеру. Дефицит на "
    "едином рынке гонит цену вверх. Товар заморожен до конца торгов.\n\n"

    "<b>🛒 7. Биржа — единая, со всем миром</b>\n"
    "Раздел «Торги» — общий стакан для игроков ВСЕХ чатов:\n"
    "• <u>Купить</u> — берёшь чужие лоты продажи.\n"
    "• <u>Продать</u> — выставляешь свой товар (он замораживается).\n"
    "• <u>Заявки «куплю» / Куплю</u> — задаёшь спрос: золото идёт в залог, "
    "тебе продают.\n"
    "Цену и кол-во вводишь сам (в коридоре). Ордер сразу сводится со встречными. "
    f"Налог 5%. Скупка одного товара — до {balance.BOURSE_BUY_LIMIT} шт за "
    f"{balance.BOURSE_BUY_WINDOW_H}ч (анти-абуз). «📊 Цены» — спрос/предложение.\n\n"

    "<b>🏪 8. Базар — единые цены мира</b>\n"
    "Оптовая цена ОДНА на весь мир: завалят товаром — просядет у всех, "
    "дефицит/ярмарка — взлетит. Купец и аукцион считают по базару — лови "
    "момент.\n\n"

    "<b>━ РОСТ ━</b>\n\n"

    "<b>⭐ 9. Репутация и уровень</b>\n"
    "Репутация растёт со сбыта — открывает пристройки и манит богачей. "
    "«Улучшить таверну» поднимает уровень: больше вместимости, дохода, бригад.\n\n"

    "<b>⚒ 10. Кузница и снаряга</b>\n"
    "Заказываешь шапку, броню, оружие, амулет. Надетое ускоряет вылазки, растит "
    "добычу, доход, удачу и силу в бою. Повторный заказ поднимает ярус. Оружие "
    "куётся из слитков.\n\n"

    "<b>🏹 11. Охота</b>\n"
    "«Персонаж → Охота»: бьёшь зверьё снарягой (урон/крит/броня). Видишь шанс и "
    "добычу заранее. Победа — мясо/шкуры/золото/трофеи; поражение — раны. "
    "HP тратится и регенится; раненый — отлёживайся или лечись едой.\n\n"

    "<b>━ ПЛЮШКИ ━</b>\n\n"

    "<b>🎁 12. Новосёл</b>\n"
    "Пока таверна ≤ ур.2: стартовый сундук, поблажки (дешевле работники, "
    "+добыча) и «Грамота» — задания за первые шаги с наградами.\n\n"

    "<b>🍻 13. Бонус дня «опохмел»</b>\n"
    "Каждое утро в <b>10:00 МСК</b> выпадает баф на выбор (берёшь когда хочешь, "
    "действует 4 ч): +доход, +добыча, быстрее ходки, крепче в бою и т.д.\n\n"

    "<b>🎪 14. Ярмарка</b>\n"
    "Раз в день купцы съезжаются — спрос <code>×2</code> на пару часов. Анонс "
    "падает в чат заранее: набей погреб и продай втридорога.\n\n"

    "<b>🎲 15. Подкидыш</b>\n"
    "Иногда в чат падает «что-то потерялось» — кто первый нажал «Поднять», "
    "тот и забрал.\n\n"

    "<blockquote>📍 В личке — кнопками; в чате — словом «гг» (команды: "
    "«гг помощь»). Готово что-то — уведомление с кнопкой придёт в чат. "
    "Забудешь зайти — напомним.</blockquote>\n"
    "<tg-spoiler>P.S. Трезвым тут делать нечего.</tg-spoiler>"
) + CHANNEL_FOOTER

ALREADY_REGISTERED = "У тебя уже есть кабак, забыл? Вот он:"


def _rel_label(v: int) -> str:
    if v >= 40:
        return "души не чает ❤️"
    if v >= 15:
        return "уважает 🙂"
    if v > 0:
        return "приглядывается 👀"
    if v > -15:
        return "косится 😒"
    if v > -40:
        return "недоволен 😠"
    return "люто ненавидит 😡"


def _faction_label(v: int) -> str:
    if v >= 50:
        return "в доску свои 🤝"
    if v >= 25:
        return "благоволят 🙂"
    if v > 0:
        return "терпят 😐"
    if v > -25:
        return "косо смотрят 😒"
    return "вне закона ☠️"


def citizens_screen(player) -> str:
    """Репутация игрока у горожан и фракций (видимая память)."""
    from bot.game import factions, npc

    from bot.game import perks

    st = player.story or {}
    parts = ["👥 <b>ГОРОЖАНЕ НЕДОЛИВСКА</b>", ""]

    known = [(nid, v) for nid, v in st.get("npc_rel", {}).items() if v != 0]
    if known:
        parts += _branch("ОТНОШЕНИЯ", [
            f"{npc.label(nid)} — {_rel_label(v)}"
            for nid, v in sorted(known, key=lambda x: -x[1])
        ])
    else:
        parts.append("«Тебя тут пока не знают. Поживёшь — приметят»")

    facs = [(f, v) for f, v in st.get("faction", {}).items() if v != 0]
    if facs:
        parts += ["", *_branch("ФРАКЦИИ", [
            f"{factions.name(f)} — {_faction_label(v)}"
            for f, v in sorted(facs, key=lambda x: -x[1])
        ])]

    active = perks.active_perks(player)
    if active:
        parts += ["", *_branch("ПРИВИЛЕГИИ", active)]

    # Живой город: сколько душ каких сословий населяют Недоливск.
    counts: dict[str, int] = {}
    for c in npc.CATALOG.values():
        counts[c.estate] = counts.get(c.estate, 0) + 1
    pop = [f"{npc.estate_label(e)} — {n}"
           for e, n in sorted(counts.items(), key=lambda x: -x[1])]
    parts += ["", *_branch(f"НАСЕЛЕНИЕ · {len(npc.CATALOG)} душ", pop)]
    return "\n".join(parts)


def _power_bar(v: int) -> str:
    fill = min(5, abs(v) // 20)
    return ("▰" * fill + "▱" * (5 - fill))


def _mood_label(v: int) -> str:
    if v >= 40:
        return "😀 приподнятое"
    if v >= 10:
        return "🙂 доброе"
    if v > -10:
        return "😐 обычное"
    if v > -40:
        return "😟 хмурое"
    return "😠 мрачное"


def city_screen(city) -> str:
    """Расклад сил фракций, настроение и текущая городская ситуация."""
    from bot.game import city as citymod
    from bot.game import factions

    parts = ["🏛 <b>НЕДОЛИВСК СЕГОДНЯ</b>", ""]
    sit = citymod.current(city)
    if sit is not None:
        parts += [f"«{sit.emoji} {sit.label} — в самом разгаре»", ""]
    parts += _branch("НАСТРОЕНИЕ", [_mood_label(citymod.mood_value(city))])
    fp = {f: v for f, v in (city.faction_power or {}).items() if v}
    if fp:
        parts += ["", *_branch("РАСКЛАД СИЛ", [
            f"{factions.name(f)} {_power_bar(v)} {v}"
            for f, v in sorted(fp.items(), key=lambda x: -x[1])
        ])]
        parts += ["", "<i>Кто заберёт власть — решают ваши дела в городе.</i>"]
    else:
        parts += ["", "«Тишь да гладь — фракции дремлют. Пока»"]
    return "\n".join(parts)


def _market_flavor(hi: float, lo: float, fair: bool) -> str:
    if fair:
        return "Ярмарка гудит — гости при деньгах, товар расхватывают"
    if hi >= 0.12:
        return "Купцы рыщут — на что-то взлетел спрос, дерут втридорога"
    if lo <= -0.12:
        return "Лавки ломятся товаром — оптовики воротят нос и сбивают цену"
    if hi >= 0.05 or lo <= -0.05:
        return "Рынок шевелится — где-то цены дрогнули, торг пошёл живее"
    return "На базаре спокойно — цены держатся, торг идёт неспешно"


def market_screen(world) -> str:
    """Единый опт: глобальные цены по товарам с трендом (завал/дефицит) и ярмаркой.
    Цены ОДНИ для всех чатов — их двигают сделки всего мира."""
    from bot.game import market as marketmod
    from bot.game import production as prod
    from bot.game import world as wld

    fair = wld.is_fair()
    fairmult = balance.TRADE_FAIR_FV_MULT if fair else 1.0
    rows, devs = [], []
    for key, g in sorted(prod.GOODS.items(), key=lambda kv: kv[1].price):
        f = marketmod.factor(world, key)
        price = max(1, int(round(g.price * fairmult * f)))
        dev = price / g.price - 1
        devs.append(dev)
        if dev > 0.05:
            arrow = f"📈 +{round(dev * 100)}%"
        elif dev < -0.05:
            arrow = f"📉 −{round(-dev * 100)}%"
        else:
            arrow = "➖ ровно"
        rows.append(f"{g.emoji} {g.name} — {price} 🪙 · {arrow}")

    flavor = _market_flavor(max(devs), min(devs), fair)
    parts = ["🏪 <b>ЕДИНЫЙ БАЗАР НЕДОЛИВСКА</b>", "", f"«{flavor}»", ""]
    if fair:
        parts += ["🎪 Ярмарка: опт +20%, купцы съезжаются", ""]
    parts += _branch("ОПТОВЫЕ ЦЕНЫ", rows)
    parts += ["", "<i>Рынок один на весь мир: цены двигают сделки всех городов "
              "сразу. Заваливаешь товаром — цена падает у всех; раскупают — растёт. "
              "Кто качнул рынок — гляди в Хронике.</i>"]
    return "\n".join(parts)


def chronicle_screen(entries: list[str]) -> str:
    """Летопись города — лента заметных событий."""
    if not entries:
        return (
            "📜 <b>ХРОНИКИ НЕДОЛИВСКА</b>\n\n"
            "«Летопись чиста, как совесть младенца — пока тут не стряслось "
            "ничего, достойного пера»"
        )
    # Подпись к фото ≤1024, поэтому строки подрезаем.
    return "\n".join([
        "📜 <b>ХРОНИКИ НЕДОЛИВСКА</b>",
        "",
        *_branch("ЗАПИСИ", [e[:90] for e in entries[:10]]),
    ])


def craft_line(player) -> str:
    """Строка о состоянии заказа в кузнице для экрана персонажа."""
    from bot.game import items as it
    from bot.game import logic

    state, minutes = logic.craft_state(player)
    if state == "active":
        item_id, tier = it.parse_entry(player.craft_item)
        item = it.CATALOG.get(item_id)
        name = f"{item.name} {it.TIER_STARS[tier]}" if item else "вещь"
        return f"⚒ Мастер куёт «{name}» — ещё {minutes // 60} ч {minutes % 60} мин."
    if state == "ready":
        return "🎁 Мастер закончил заказ — забери вещь!"
    return ""


def _fmt_minutes(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    return f"{m} мин"


def fair_pre_announce(minutes_left: int) -> str:
    """Анонс в общий чат за несколько часов до ярмарки — нагнетаем ажиотаж."""
    return (
        "📯 <b>НУ ЧЁ, АЛКАШНЯ, УШИ РАСКРОЙ!</b>\n\n"
        "Гонец-ярыжка прискакал на взмыленной кляче, чуть ебало о плетень не "
        f"расшиб, и блажит на всю площадь, аж вороны срутся: чрез "
        f"<b>{_fmt_minutes(minutes_left)}</b> грянет в Недоливске <b>ЯРМАРКА</b>, "
        "мать её за ногу через коромысло! 🍻\n\n"
        "Понаедет купчина пузатый при злате, мужичьё после пахоты с трубами "
        "горящими, да бабы похмельные за мёдом — и вся эта пьянь будет жрать да "
        f"квасить так, что спрос вздрючит на <code>×{balance.FAIR_DEMAND_MULT:g}</code>, "
        "бляха-муха.\n\n"
        "<blockquote>Кто бочками запасся — тот завтра в шелках да златом "
        "подтираться будет. А кто проспал, хуесос ленивый — соси лапу да "
        "опохмеляйся водой из лужи, аки пёс шелудивый.</blockquote>\n\n"
        "Так что хорош жопу мять да слюни пускать! Гони бригады за сырьём, вари, "
        "томи, набивай погреба под самую пробку, покуда время терпит. "
        "<i>Купчина ждать не станет — ему насрать на твою синьку да лень-матушку.</i>"
    )


def fair_open_announce() -> str:
    """Анонс открытия ярмарки — зовём всех торговать прямо сейчас."""
    return (
        "🎪 <b>ВСЁ, ПОНЕСЛАСЬ ПИЗДА ПО КОЧКАМ! ЯРМАРКА!</b>\n\n"
        "Площадь гудит аки улей, в который ссыкнули, гармонь пилит, народ валит "
        "стадом — и каждый при кошеле, зенки залиты, рожа красная! Трубы у всех "
        "горят, глотки пересохли, спрос на бухло да закусь — "
        f"<code>×{balance.FAIR_DEMAND_MULT:g}</code> на цельных "
        f"<b>{balance.FAIR_DURATION_HOURS} часа</b>! 🍺🍖\n\n"
        "<blockquote>Ныне или никогда, хозяин. Другого такого бухача не будет.</blockquote>\n\n"
        "Жми «<b>гг</b>» да сливай товар, покуда купчина при злате и не нажрался "
        "в дрова окончательно. Бочки сами себя, блядь, не продадут — шевели "
        "поршнями! <i>Кто щас дрыхнет — тот завтра локти грызёт да волком на луну "
        "воет, трезвый и нищий.</i>"
    )


def _season_perks(s) -> str:
    """Что сезон даёт — по данным сезона, в трактирном стиле (└-строки)."""
    parts = []
    d = round((s.demand_mult - 1) * 100)
    if d > 0:
        parts.append(f"🍺 Жажда +{d}% — пьянь прёт в кабак, наливай не зевай")
    elif d < 0:
        parts.append(f"🍺 Спрос {d}% — народ жмётся по избам, гуляк меньше")
    boosted = [r for r, m in s.yield_mults.items() if m > 1]
    if boosted:
        res = " ".join(f"{RESOURCE_EMOJI[r]}{RESOURCE_NAMES[r].lower()}" for r in boosted)
        parts.append(f"⛏ Прёт само в руки: {res} — бригады гребут с горкой")
    if s.default_yield < 1:
        parts.append(
            f"⛏ Добыча в целом −{round((1 - s.default_yield) * 100)}% — "
            "мёрзни да кляни погоду")
    return "\n".join(f"└ {p}" for p in parts) or "└ погода как погода, без чудес"


def season_announce(s) -> str:
    """Анонс смены сезона в чат."""
    return (
        f"{s.emoji} <b>{s.name.upper()} НА ДВОРЕ, НЕДОЛИВСК!</b>\n\n"
        f"{s.blurb[0].upper()}{s.blurb[1:]}.\n\n"
        f"<b>ЧТО С ЭТОГО:</b>\n{_season_perks(s)}\n\n"
        "Подстраивай дела под погоду, кабатчик, — кто не чешется, тот и пролетает."
    )


def holiday_announce(h) -> str:
    """Анонс праздника в чат."""
    return (
        f"{h.emoji} <b>{h.name.upper()}!</b>\n\n"
        f"{h.blurb[0].upper()}{h.blurb[1:]}! Спрос нынче бешеный — тащи всё "
        "пойло на продажу, второго такого дня ждать целый год."
    )


def fair_close_announce() -> str:
    """Анонс закрытия ярмарки — итог и зацепка на следующую."""
    return (
        "🌙 <b>Всё, пиздец котёнку, лавочка закрыта.</b>\n\n"
        "Купчина уполз раком по домам, гармонист в сене дрыхнет да слюни пускает, "
        "последний синяк допел, облевал лавку и сдох под ней до утра. Опустела "
        "площадь до завтрева.\n\n"
        "<blockquote>Кто бочки сбыть успел — звенит златом и дрыхнет, сука, "
        "довольный аки боров. А кто ушами прохлопал — <tg-spoiler>тот сидит "
        "трезвый, злой, с пустым карманом да рожей кислой</tg-spoiler>.</blockquote>\n\n"
        "Точи бочки, готовь запас, братие-алкашня — ярмарка ещё воротится, "
        "никуда, родимая, не денется. <i>А покуда — накати по последней да на "
        "боковую, рожа ты пьяная.</i>"
    )


def _build_line(player: Player) -> str:
    """Строка о текущей стройке для экрана таверны."""
    from bot.game import buildings as bld

    state, minutes = bld.build_state(player)
    if state == "active":
        b = bld.CATALOG.get(player.build_item)
        name = b.name if b else "пристройка"
        return f"🏗 Строится {name} — ещё {_fmt_minutes(minutes)}"
    if state == "ready":
        b = bld.CATALOG.get(player.build_item)
        return f"🏗 {b.name if b else 'Пристройка'} достроена — загляни в Пристройки!"
    return ""


def _cost_line(cost: dict, player: Player) -> str:
    """Стоимость по словарю, без крестов: хватает — «🪵 160»; не хватает —
    «🌾 40/60» (дробь = есть/надо, сразу видно, сколько ещё донести)."""
    emoji = {"gold": "🪙", **RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    parts = []
    for key, need in cost.items():
        if not need:
            continue
        have = player.gold if key == "gold" else inventory.get(player, key)
        ico = emoji.get(key, key)
        parts.append(f"{ico} {need}" if have >= need else f"{ico} {have}/{need}")
    return " · ".join(parts)


def buildings_screen(player: Player, tavern: Tavern) -> str:
    from bot.game import buildings as bld

    items = []
    for bid in bld.ORDER:
        b = bld.CATALOG[bid]
        if bld.is_built(tavern, bid):
            status = "✓ построено"
        elif player.build_item == bid:
            _, m = bld.build_state(player)
            status = f"🏗 строится, ещё {_fmt_minutes(m)}"
        elif bld.missing_requirements(tavern, b):
            req = ", ".join(r.name for r in bld.missing_requirements(tavern, b))
            status = f"🔒 нужна: {req}"
        else:
            status = "доступна к стройке"
        items.append(f"{b.emoji} {b.name} — {status}")
    return "\n".join([
        "🏗 <b>ПРИСТРОЙКИ</b>",
        "",
        "«Каждая открывает своё производство. Деньги и сырьё — вперёд»",
        "",
        *_branch("ПОСТРОЙКИ", items),
    ])


def building_detail(building, player: Player, tavern: Tavern) -> str:
    from bot.game import buildings as bld

    head = f"{building.emoji} <b>{building.name}</b>\n<i>{building.description}</i>\n"
    gives = f"Откроет: {building.unlocks}\n" if building.unlocks else ""

    if bld.is_built(tavern, building.id):
        return head + gives + "\n✓ Уже построено. Работает."

    miss = bld.missing_requirements(tavern, building)
    if miss:
        req = ", ".join(r.name for r in miss)
        return head + gives + f"\n🔒 Сначала построй: {req}."

    if bld.rep_locked(tavern, building):
        return head + gives + (
            f"\n🔒 Нужна репутация {building.req_reputation} "
            f"(у тебя {tavern.reputation}). Поднимай заведение."
        )

    state, m = bld.build_state(player)
    if state != "none":
        return head + gives + (
            "\n🏗 Сейчас уже идёт другая стройка — одна за раз. "
            f"Освободятся работники через {_fmt_minutes(m)}."
        )

    return (
        head + gives +
        f"\nСтройка: {building.build_hours} ч\n"
        f"Цена: {_cost_line(building.cost, player)}"
    )


def build_started(building, hours: int) -> str:
    return (
        f"🏗 Заложили фундамент под <b>{building.name}</b>. "
        f"Артель обещает управиться за {hours} ч — и не факт, что не соврёт."
    )


def build_not_enough(building, player: Player) -> str:
    return (
        f"😕 На <b>{building.name}</b> не хватает.\n"
        f"Надо: {_cost_line(building.cost, player)}\n"
        "Гони работников за сырьём и возвращайся."
    )


def build_ready_notification(building) -> str:
    return (
        f"{building.emoji} <b>{building.name} достроена!</b>\n"
        "Загляни в Пристройки — пора пускать в дело."
    )


# ===== Производство =====

def _recipe_line(player: Player, emoji: str, name: str, out_qty: int,
                 time_str: str, inputs: dict) -> str:
    """Рецепт одной строкой: «🍖 Жаркое ×12 · 6 ч» + «из: 🥩 3/6 · 🌾 6» — наличие
    сразу в рецепте (дробь = есть/надо), без отдельной строки сверки."""
    return (f"{emoji} <b>{name}</b> ×{out_qty} · {time_str}\n"
            f"   из: {_cost_line(inputs, player)}")


def production_screen(building, player: Player, tavern: Tavern) -> str:
    from bot.game import production as prod

    head = f"{building.emoji} <b>{building.name}</b>\n<i>{building.description}</i>"
    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    L = tavern.level

    if building.id in prod.GRIND:  # мельница/горн: сырьё → полуфабрикат
        state, minutes = prod.state(tavern, building.id)
        status = (f"⏳ Работает — ещё {_fmt_minutes(minutes)}." if state == "active"
                  else "📦 Готово — забирай на склад!" if state == "ready"
                  else "😴 Простаивает — выбери, что молоть.")
        recipes = [
            _recipe_line(player, ico.get(rc, rc), balance.GOODS_NAMES.get(rc, rc),
                         prod.grind_output(building.id, rc, L), f"{mins} мин",
                         prod.grind_inputs(building.id, rc, L))
            for rc, (_i, mins, _o) in prod.GRIND[building.id].items()]
        made = " · ".join(f"{ico.get(rc, rc)} {inventory.get(player, rc)}"
                          for rc in prod.GRIND[building.id])
        return "\n".join([head, "", status, ""] + recipes + ["", f"📦 Сделано: {made}"])

    if building.id in prod.RECIPES:  # пекарня/коптильня/сыроварня: вход → товар
        prods = tavern.products or {}
        state, minutes = prod.state(tavern, building.id)
        if state == "active":
            rc = (tavern.production.get(building.id) or {}).get("recipe")
            nm = prod.GOODS[rc].name if rc in prod.GOODS else "товар"
            status = f"⏳ Готовится {nm} — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🍽 Готово — забирай в погреб!"
        else:
            status = "😴 Простаивает — выбери, что готовить."
        stock = " · ".join(f"{prod.GOODS[rc].emoji} {prods.get(rc, 0)}"
                           for rc in prod.RECIPES[building.id])
        recipes = [
            _recipe_line(player, prod.GOODS[rc].emoji, prod.GOODS[rc].name,
                         prod.recipe_output(building.id, rc, L),
                         f"{prod.recipe_hours(building.id, rc)} ч",
                         prod.recipe_inputs(building.id, rc, L))
            for rc in prod.RECIPES[building.id]]
        return "\n".join([head, "", f"🛢 В погребе: {stock}", status, ""] + recipes)

    if building.id == "brewery":
        prods = tavern.products or {}
        stock = " · ".join(f"{prod.ALE_STARS[t]} {prods.get(f'ale{t}', 0)}" for t in (1, 2, 3))
        phase, minutes = prod.brew_phase(tavern)
        bt = int(tavern.production["brewery"]["tier"]) if phase != "empty" else 0
        if phase == "fermenting":
            status = f"⏳ Бродит {prod.ALE_STARS[bt]} — ещё {_fmt_minutes(minutes)}."
        elif phase == "ready":
            extra = " или выдержи (риск +ярус)" if bt < 3 else ""
            status = f"🍺 {prod.ALE_STARS[bt]} готов — разливай{extra}!"
        elif phase == "aging":
            status = (f"🛢 Выдержка {prod.ALE_STARS[bt]} → {prod.ALE_STARS[min(3, bt+1)]} — "
                      f"ещё {_fmt_minutes(minutes)}.")
        elif phase == "ripe":
            status = (f"⏰ Выдержка дошла! Разливай за {_fmt_minutes(minutes)} — "
                      "иначе перекиснет.")
        elif phase == "overripe":
            status = "⚠️ Перекисает! Разливай немедля — ярус упадёт."
        else:
            status = "😴 Чаны пусты — выбери, что варить."
        recipes = [
            _recipe_line(player, "🍺", f"Эль {prod.ALE_STARS[t]}", prod.brew_output(t, L),
                         f"{prod.brew_hours(t)} ч", prod.brew_inputs(t, L))
            for t in (1, 2, 3)]
        return "\n".join([head, "", f"🛢 Погреб: {stock}", status, ""] + recipes)

    if building.id == "meadery":
        prods = tavern.products or {}
        stock = f"🍶 {prods.get('mead', 0)} · 🌿 {prods.get('sbiten', 0)}"
        state, minutes = prod.state(tavern, "meadery")
        if state == "active":
            rc = tavern.production["meadery"].get("recipe", "mead")
            status = f"⏳ Готовится {prod.DRINKS[rc].name} — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🍶 Готово — разливай в погреб!"
        else:
            status = "😴 Котлы остыли — выбери, что варить."
        recipes = [
            _recipe_line(player, prod.DRINKS[rc].emoji, prod.DRINKS[rc].name,
                         prod.meadery_output(rc, L), f"{prod.meadery_hours(rc)} ч",
                         prod.meadery_inputs(rc, L))
            for rc in ("mead", "sbiten")]
        return "\n".join([head, "", f"🛢 Погреб: {stock}", status, ""] + recipes
                         + ["", "<i>Берут состоятельные — репутация решает.</i>"])

    if building.id == "kitchen":
        food = (tavern.products or {}).get("roast", 0)
        state, minutes = prod.state(tavern, "kitchen")
        status = (f"⏳ На вертеле — ещё {_fmt_minutes(minutes)}." if state == "active"
                  else "🍖 Жаркое готово — в кладовую!" if state == "ready"
                  else "😴 Очаг остыл — поставь готовить.")
        recipe = _recipe_line(player, "🍖", "Жаркое", prod.kitchen_output("roast", L),
                              f"{prod.kitchen_hours('roast')} ч", prod.kitchen_inputs("roast", L))
        return "\n".join([head, "", f"🍖 В кладовой: {food}", status, "", recipe,
                          "", "<i>Сытые гости платят за еду сверх выпивки.</i>"])

    if building.id == "winery":
        wine = (tavern.products or {}).get("wine", 0)
        state, minutes = prod.state(tavern, "winery")
        status = (f"⏳ Бродит — ещё {_fmt_minutes(minutes)}." if state == "active"
                  else "🍷 Вино готово — разливай в погреб!" if state == "ready"
                  else "😴 Бочки пусты — поставь вино.")
        recipe = _recipe_line(player, "🍷", "Вино", prod.winery_output("wine", L),
                              f"{prod.winery_hours('wine')} ч", prod.winery_inputs("wine", L))
        return "\n".join([head, "", f"🍷 В погребе: {wine}", status, "", recipe,
                          "", "<i>Самый дорогой напиток — берут только богачи.</i>"])

    return head + "\nПроизводство этого здания — скоро."


def winery_not_enough(recipe: str, cin: dict) -> str:
    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    need = " ".join(f"{ico.get(r, r)}{q}" for r, q in cin.items())
    return f"😕 На вино не хватает: {need}. Шли бригаду за ягодами."


def winery_ready_notification() -> str:
    return (
        "🍷 <b>Вино дошло!</b> Разлей в погреб — "
        "богатая публика ценит хорошее вино."
    )


def kitchen_not_enough(recipe: str, cin: dict) -> str:
    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    need = " ".join(f"{ico.get(r, r)}{q}" for r, q in cin.items())
    return f"😕 На блюдо не хватает: {need}. Пошли бригаду на охоту."


def kitchen_ready_notification() -> str:
    return (
        "🍖 <b>Жаркое готово!</b> Неси в кладовую — "
        "голодные гости уже принюхиваются."
    )


def meadery_not_enough(recipe: str, cin: dict) -> str:
    from bot.game import production as prod

    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    need = " ".join(f"{ico.get(r, r)}{q}" for r, q in cin.items())
    return f"😕 На «{prod.DRINKS[recipe].name}» не хватает: {need}. Доготовь сырьё."


def meadery_ready_notification(recipe: str) -> str:
    from bot.game import production as prod

    d = prod.DRINKS[recipe]
    return (
        f"{d.emoji} <b>{d.name} поспел(а)!</b> Разлей в погреб — "
        "состоятельная публика уже облизывается."
    )


def brew_not_enough(tier: int, cin: dict) -> str:
    from bot.game import production as prod

    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    need = " ".join(f"{ico.get(r, r)}{q}" for r, q in cin.items())
    return f"😕 На {prod.ALE_STARS[tier]} не хватает: {need}. Доготовь сырьё."


def brew_ready_notification(tier: int) -> str:
    from bot.game import production as prod

    return (
        f"🍺 <b>Эль {prod.ALE_STARS[tier]} доварился!</b> "
        "Разлей в погреб — или поставь на выдержку, рискни поднять ярус."
    )


def brew_aged_notification(tier: int) -> str:
    from bot.game import production as prod

    return (
        f"⏰ <b>Выдержка {prod.ALE_STARS[tier]} дошла!</b> "
        "Разливай скорее — передержишь, и бочка перекиснет."
    )


def brew_claimed(outcome: str, tier: int, qty: int) -> str:
    from bot.game import production as prod

    star = prod.ALE_STARS.get(tier, "")
    if outcome == "matured":
        return f"🍀 Выдержка удалась! Эль поднялся до {star}: +{qty} в погреб."
    if outcome == "soured":
        return f"😒 Перекисло — эль осел до {star}: +{qty} в погреб. Бывает."
    if outcome == "lost":
        return "💀 Прокисло вусмерть. Вся бочка коту под хвост — выдержка это риск."
    return f"🍺 Разлито: {star} +{qty} в погреб."


def mill_started(amount: int, minutes: int) -> str:
    return (
        f"🌾 Жернова закрутились. Будет ~{amount} 🌱 солода через "
        f"{_fmt_minutes(minutes)}. Мельник уже тянется к кружке."
    )


def mill_not_enough(cin: dict) -> str:
    return (
        f"😕 Зерна мало: на помол нужно 🌾 {cin['grain']}. "
        "Гони работников в поля."
    )


def malt_ready_notification() -> str:
    return (
        "🌱 <b>Солод смолот!</b> Забирай с мельницы — "
        "и в пивоварню, пока мыши не добрались."
    )


def recipe_not_enough(recipe: str, cin: dict) -> str:
    """Универсальное «не хватает сырья» для грайндеров и рецептурных пристроек."""
    from bot.game import production as prod
    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    need = " ".join(f"{ico.get(r, r)}{q}" for r, q in (cin or {}).items())
    name = prod.GOODS[recipe].name if recipe in prod.GOODS else \
        balance.GOODS_NAMES.get(recipe, recipe)
    return f"😕 На «{name}» не хватает: {need}. Шли бригаду за сырьём."


def recipe_ready_notification(recipe: str) -> str:
    """Универсальное «готово» для пекарни/коптильни/сыроварни."""
    from bot.game import production as prod
    g = prod.GOODS.get(recipe)
    if g is None:
        return "🍽 <b>Готово!</b> Забирай в погреб."
    return f"{g.emoji} <b>{g.name} готово!</b> Неси в погреб — гости проголодались."


# Реактивная атмосфера: сочные строки под текущее состояние кабака и города.
_FLAVOR = {
    "fair": [
        "Площадь гудит, гости валят валом — наливай, не зевай!",
        "Ярмарка! Народ при деньгах и при жажде — куй барыш, пока куётся.",
    ],
    "thieves_rampant": [
        "По углам шныряют тёмные рожи — держи кассу ближе к телу.",
        "Ворьё обнаглело вконец: считай монеты дважды, кабатчик.",
    ],
    "curfew": [
        "Стража лютует, патрули на каждом шагу — гости жмутся по домам.",
        "Комендантский час: зал пустеет затемно, хоть волком вой.",
    ],
    "merchant_boom": [
        "Купцы гуляют от души, золото льётся рекой — твой час настал!",
        "Торговый бум: гости при мошне и в настроении кутить до утра.",
    ],
    "crown_taxes": [
        "Сборщики податей вынюхивают каждую монету — прячь выручку.",
        "Корона трясёт поборами, в кассе будто дыра прохудилась.",
    ],
    "temperance": [
        "Пост: народ кается и пьёт через раз, богомольные зануды.",
        "Церковь загнала паству в трезвость — спрос просел, тоска.",
    ],
    "mood_high": [
        "Кабак гудит, рожи довольные, эль течёт рекой.",
        "Веселье в самом разгаре — гогот стоит до самого потолка.",
    ],
    "mood_low": [
        "Народ хмурый, пьют молча, будто на похоронах.",
        "Над городом висит тоска — и в кабаке тише стоячей воды.",
    ],
    "poor": [
        "В мошне ветер свищет — пора шевелиться, голодранец.",
        "Касса пуста, как башка завсегдатая. Иди работай, хозяин.",
    ],
    "brigades": [
        "Работяги вернулись, гомонят у входа — забери добычу!",
        "Бригады свалили мешки у порога — разбирай, пока цело.",
    ],
    "winter": [
        "За окном метёт, у очага жмётся продрогший до костей люд.",
        "Стужа лютая — гости отогреваются да требуют ещё по одной.",
    ],
    "summer": [
        "Духота, все требуют чего похолоднее да побольше.",
        "Жара выгнала народ из домов — в кабаке не протолкнуться.",
    ],
    "autumn": [
        "Урожай свезли — гуляет народ, пока закрома полны.",
        "Осень, мужики при деньгах после жатвы — знай наливай.",
    ],
    "spring": [
        "Капель за окном, мужики тянутся пропустить по первой.",
        "Весна разморозила дороги — потянулись захожие гости.",
    ],
    "default": [
        "Скрипят половицы, воняет элем и мокрой псиной.",
        "Обычный день: чад, гомон да кислый дух браги.",
    ],
}


def _section(label: str) -> str:
    # Левый заголовок без длинных дашей — на узком экране не «съезжает».
    return f"<b>{label}</b>"


def _mood_short(v: int) -> str:
    if v >= 40:
        return "😀 Город гуляет"
    if v >= 10:
        return "🙂 Настроение доброе"
    if v > -10:
        return "😐 Настроение обычное"
    if v > -40:
        return "😟 Город хмур"
    return "😠 Город мрачен"


def _flavor_line(player, tavern, chat_id, seasonmod, citymod) -> str:
    sid = citymod.cached_situation_id(chat_id)
    mood = citymod.cached_mood(chat_id)
    c = logic.expedition_counts(player, tavern)
    if wld.is_fair():
        key = "fair"
    elif sid in _FLAVOR:
        key = sid
    elif mood is not None and mood >= 40:
        key = "mood_high"
    elif mood is not None and mood <= -30:
        key = "mood_low"
    elif player.gold < 50:
        key = "poor"
    elif c.ready:
        key = "brigades"
    else:
        key = seasonmod.current().id
    return random.choice(_FLAVOR.get(key, _FLAVOR["default"]))


def _production_lines(tavern: Tavern) -> list[str]:
    from bot.game import production as prod

    p = tavern.production or {}
    out = []
    if "brewery" in p:
        phase, m = prod.brew_phase(tavern)
        st = prod.ALE_STARS.get(int(p["brewery"].get("tier", 1)), "")
        if phase == "fermenting":
            out.append(f"🍺 Эль {st} бродит — {_fmt_minutes(m)}")
        elif phase == "ready":
            out.append(f"🍺 Эль {st} готов — разливай!")
        elif phase == "aging":
            out.append(f"🛢 Эль {st} на выдержке — {_fmt_minutes(m)}")
        elif phase in ("ripe", "overripe"):
            out.append(f"🛢 Эль {st} дошёл — разливай скорей!")
    # Остальные пристройки — обобщённо (грайндеры → полуфабрикат, рецептурные → товар)
    for bid, batch in p.items():
        if bid == "brewery" or bid not in prod.PRODUCERS:
            continue
        s, m = prod.state(tavern, bid)
        if s not in ("active", "ready"):
            continue
        if bid in prod.GRIND:
            key = (batch or {}).get("out_res", "")
            emoji = balance.GOODS_EMOJI.get(key, "📦")
            name = balance.GOODS_NAMES.get(key, key or "Передел")
        else:
            key = (batch or {}).get("recipe", "")
            g = prod.GOODS.get(key)
            emoji, name = (g.emoji, g.name) if g else ("🍽", "Товар")
        if s == "active":
            out.append(f"{emoji} {name} — {_fmt_minutes(m)}")
        else:
            out.append(f"{emoji} {name} готово — забирай!")
    return out


def _producer_counts(tavern: Tavern) -> tuple[int, int]:
    """(в работе, готово) по всем пристройкам — для компактной сводки."""
    from bot.game import production as prod
    active = ready = 0
    for bid in (tavern.production or {}):
        if bid not in prod.PRODUCERS:
            continue
        if bid == "brewery":
            ph, _ = prod.brew_phase(tavern)
            if ph in ("fermenting", "aging"):
                active += 1
            elif ph in ("ready", "ripe", "overripe"):
                ready += 1
        else:
            s, _ = prod.state(tavern, bid)
            active += s == "active"
            ready += s == "ready"
    return active, ready


def _world_lines(chat_id, seasonmod, citymod) -> list[str]:
    s = seasonmod.current()
    hol = seasonmod.holiday()
    if hol is not None:
        w1 = f"{hol.emoji} {hol.name}! спрос ×{balance.HOLIDAY_DEMAND:g}"
    elif s.demand_mult > 1:
        w1 = f"{s.emoji} {s.name} поднимает спрос"
    elif s.demand_mult < 1:
        w1 = f"{s.emoji} {s.name} снижает спрос"
    else:
        w1 = f"{s.emoji} {s.name} — спрос обычный"
    out = [w1]
    from bot.game import production, worldevent
    ev = worldevent.active()
    if ev is not None:   # активное мировое событие — первым, с таймером и эффектом
        summ = worldevent.effect_summary(ev)
        fg = worldevent.fashion_good()
        if fg:           # мода на товар — показываем его имя и премию к цене
            g = production.GOODS.get(fg)
            gname = g.name if g else fg
            summ = f"🔥 в моде {gname} +{round((ev.good_price - 1) * 100)}% цена"
        out.insert(0, f"{ev.emoji} {ev.name} ({summ}) — "
                      f"ещё {_fmt_left_h(worldevent.active_until())}")
    if wld.is_fair():
        out.append(f"🎪 Ярмарка — ещё {_fmt_minutes(wld.fair_minutes_left())}")
    mood = citymod.cached_mood(chat_id)
    if mood is not None:
        out.append(_mood_short(mood))
    clabel = citymod.cached_label(chat_id)
    out.append(clabel if clabel else "🏛 В городе тихо")
    return out


def _upgrade_progress(player: Player, tavern: Tavern) -> str:
    if tavern.level >= balance.MAX_LEVEL:
        return "🏆 Выше строить некуда — ты легенда Недоливска."
    cost = balance.upgrade_cost(tavern.level)
    pcts = []
    for k in ("gold", "wood", "grain", "hops"):
        have = player.gold if k == "gold" else inventory.get(player, k)
        need = cost.get(k, 0)
        pcts.append(min(1.0, have / need) if need else 1.0)
    pct = sum(pcts) / len(pcts)
    filled = round(pct * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    return f"🔨 Перестройка {bar} {round(pct * 100)}%"


def _pending_income(tavern: Tavern) -> int:
    """Грубая оценка накопившегося пассива (к сбору)."""
    from datetime import datetime, timezone
    last = tavern.last_income_at
    if not last:
        return 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = min((datetime.now(timezone.utc) - last).total_seconds() / 3600,
                balance.INCOME_CAP_HOURS)
    return int(tavern.income_rate * hours) if hours > 0 else 0


_FIGSP = " "  # цифро-широкий пробел: ширина = ширине цифры (выравнивание колонок)


def _storage_lines(player: Player) -> list[str]:
    """ВСЕ ресурсы в ФИКСИРОВАННОЙ сетке 2 столбика — у каждого своё место (ничего
    не «прыгает», меняются только числа). Число стоит вплотную к значку, а хвост
    добивается цифро-широким пробелом — так начало 2-го столбца выровнено в Telegram."""
    inv = player.inventory or {}
    res = balance.RESOURCES
    half = (len(res) + 1) // 2
    width = max((len(str(inv.get(r, 0))) for r in res), default=1)

    def cell(r: str, pad: bool) -> str:
        n = str(inv.get(r, 0))
        s = f"{RESOURCE_EMOJI[r]} {n}"
        return s + _FIGSP * (width - len(n)) if pad else s

    rows = []
    for i in range(half):
        j = i + half
        rows.append(f"{cell(res[i], True)} · {cell(res[j], False)}"
                    if j < len(res) else cell(res[i], False))
    return rows


def _upgrade_pct(player: Player, tavern: Tavern) -> int | None:
    if tavern.level >= balance.MAX_LEVEL:
        return None
    cost = balance.upgrade_cost(tavern.level)
    pcts = []
    for k in cost:  # учитываем все позиции (с ур.5 — и камень)
        have = player.gold if k == "gold" else inventory.get(player, k)
        need = cost.get(k, 0)
        pcts.append(min(1.0, have / need) if need else 1.0)
    return round(sum(pcts) / len(pcts) * 100)


def _cellar_line(tavern: Tavern) -> str:
    from bot.game import production as prod
    prods = tavern.products or {}
    parts = [f"{prod.GOODS[k].name} {n}"
             for k, n in prods.items() if n > 0 and k in prod.GOODS]
    return " · ".join(parts) if parts else "пусто"


_HRULE = "━" * 12


def _branch(label: str, lines: list[str]) -> list[str]:
    """Секция: жирный заголовок + строки с веткой └."""
    return [f"<b>{label}</b>"] + [f"└ {ln}" for ln in lines]


def tavern_screen(player: Player, tavern: Tavern) -> str:
    from bot.game import buff as buffmod
    from bot.game import city as citymod
    from bot.game import items as it
    from bot.game import season as seasonmod

    chat_id = getattr(player, "chat_id", None)
    region = balance.REGIONS.get(player.region, player.region)
    flavor = _flavor_line(player, tavern, chat_id, seasonmod, citymod)

    # СЕЙЧАС — активные дела
    now_lines = []
    act = buffmod.active(player)
    if act is not None:  # действует баф «опохмела»
        now_lines.append(
            f"{act.emoji} Баф «{act.name}» — ещё {_fmt_minutes(buffmod.minutes_left(player))}")
    elif buffmod.offer(player) is not None:  # бонус дня ждёт активации
        now_lines.append("🎁 Бонус дня готов — забери и активируй!")
    c = logic.expedition_counts(player, tavern)
    if c.ready and c.out:
        now_lines.append(f"⛏ Бригады: {c.ready} готовы, {c.out} в пути")
        now_lines.append(f"⏳ Возврат через {_fmt_minutes(c.next_minutes)}")
    elif c.ready:
        now_lines.append(f"⛏ Бригады вернулись ({c.ready}) — забирай!")
    elif c.out:
        now_lines.append(f"⛏ Бригады в пути: {c.out}/{c.total}")
        now_lines.append(f"⏳ Возврат через {_fmt_minutes(c.next_minutes)}")
    else:
        now_lines.append("⛏ Бригады свободны — гони за добром")
    prod_lines = _production_lines(tavern)
    if len(prod_lines) > 3:  # не разводим простыню — сводка (подпись фото ≤1024)
        active, ready = _producer_counts(tavern)
        bits = []
        if active:
            bits.append(f"{active} в работе")
        if ready:
            bits.append(f"{ready} готовы — забирай")
        now_lines.append("🏭 Пристройки: " + ", ".join(bits))
    else:
        now_lines += prod_lines
    bl = _build_line(player)
    if bl:
        now_lines.append(bl)
    pct = _upgrade_pct(player, tavern)
    now_lines.append(f"🔨 Перестройка — {pct}%" if pct is not None
                     else "🏆 Выше строить некуда")

    eq = getattr(player, "equipment", None) or {}
    luck_pct = balance.lucky_chance(
        it.combat_stats(eq)["luck"] + buffmod.luck_bonus(player))

    parts = [
        f"🏡 <b>{escape(tavern.name.upper())}</b> · уровень {tavern.level}",
        f"📍 {region}",
        "",
        f"«{flavor}»",
        "",
        _HRULE,
        "<b>СЕЙЧАС</b>",
        *[f"└ {ln}" for ln in now_lines],
        _HRULE,
        "",
        *_branch("РЕСУРСЫ", [
            f"🪙 Золото — {player.gold}",
            f"💰 Доход — {tavern.income_rate}/ч",
            f"⭐ Репутация — {tavern.reputation}",
        ]),
        "",
        *_branch("ЗАВЕДЕНИЕ", [
            f"👥 Места — {tavern.capacity}",
            f"✨ Уют — {tavern.comfort}",
            f"🍀 Удача — {luck_pct}%",
            f"🎒 Снаряга — {len(eq)}/{len(it.SLOTS)}",
        ]),
        "",
        *_branch("СКЛАД", [
            *_storage_lines(player),
            f"🛢 Погреб — {_cellar_line(tavern)}",
        ]),
        "",
        *_branch("МИР", _world_lines(chat_id, seasonmod, citymod)),
    ]
    return "\n".join(parts)


def _upgrade_need_block(player: Player, tavern: Tavern) -> list[str]:
    """Секция «до перестройки» в едином стиле (└)."""
    if tavern.level >= balance.MAX_LEVEL:
        return ["🏆 Выше строить некуда — ты легенда Недоливска."]
    cost = balance.upgrade_cost(tavern.level)
    emoji = {"gold": "🪙", **RESOURCE_EMOJI}
    lines = []
    for key in cost:  # все позиции стоимости (с ур.5 добавляется камень)
        have = player.gold if key == "gold" else inventory.get(player, key)
        mark = "✅" if have >= cost[key] else "❌"
        lines.append(f"{emoji[key]} {have} / {cost[key]} {mark}")
    return _branch(f"ПЕРЕСТРОЙКА · ур. {tavern.level + 1}", lines)


def warehouse_screen(player: Player, tavern: Tavern) -> str:
    stock = [
        f"{RESOURCE_EMOJI[r]} {RESOURCE_NAMES[r]} — {inventory.get(player, r)}"
        for r in balance.RESOURCES
    ]
    parts = [
        f"📦 <b>СКЛАД «{escape(tavern.name.upper())}»</b>",
        "",
        "«Темно, пыльно, по углам крысы — что ещё не растащили»",
        "",
        f"🪙 <b>Золото — {player.gold}</b>",
        "",
        *_branch("ЗАПАСЫ", stock),
        "",
        *_upgrade_need_block(player, tavern),
    ]
    return "\n".join(parts)


def storehouse_caption(player: Player, tavern: Tavern) -> str:
    """Короткая подпись к складской ведомости (ресурсы и числа — на картинке).
    Если ресурсов больше, чем ячеек, остаток перечислили бы текстом (сейчас все
    влезают — overflow пуст)."""
    from bot.game import storehouse as sh
    parts = [
        f"📦 <b>СКЛАД «{escape(tavern.name.upper())}»</b>",
        "",
        f"🪙 <b>Золото — {player.gold}</b>",
    ]
    extra = [r for r in sh.OVERFLOW_RESOURCES if inventory.get(player, r) > 0] \
        or list(sh.OVERFLOW_RESOURCES)
    if extra:
        line = " · ".join(
            f"{RESOURCE_EMOJI[r]} {RESOURCE_NAMES[r]} {inventory.get(player, r)}"
            for r in extra)
        parts += ["", *_branch("ЕЩЁ НА СКЛАДЕ", [line])]
    parts += ["", *_upgrade_need_block(player, tavern)]
    return "\n".join(parts)


def expedition_menu(player: Player) -> str:
    tavern = player.tavern
    level = tavern.level if tavern else 1
    pay = balance.worker_pay(level)
    c = logic.expedition_counts(player, tavern)
    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}
    parts = [
        "⛏ <b>БРИГАДЫ РАБОТНИКОВ</b>",
        "",
        f"«Свободно {c.free}/{c.total} · в пути {c.out} · вернулись {c.ready}»",
    ]
    # 💡 Подсказка: на что не хватает добываемого сырья → куда слать бригад.
    # Вариант 1: каждая цель — отдельный блок, ресурсы названы словами.
    goals, _total = logic.expedition_goals(player, tavern)
    if goals:
        nm = {**RESOURCE_NAMES, **balance.GOODS_NAMES}
        parts += ["", "💡 <b>На что копить</b>"]
        for label, short in goals:
            res = " · ".join(f"{ico.get(r, r)} {nm.get(r, r)} {q}"
                             for r, q in short.items())
            parts += ["", f"<b>{label}</b>", f"   {res}"]
    parts += [
        "",
        *_branch("УСЛОВИЯ", [
            f"Ходка — {balance.EXPEDITION_HOURS} ч",
            f"Плата — {pay} 🪙 за бригаду вперёд",
        ]),
        "",
        "<i>Гони сразу несколько — кто за чем.</i>",
    ]
    return "\n".join(parts)


def expedition_no_slot() -> str:
    return (
        "Все бригады уже в деле. Больше работников нет — "
        "расти таверну, наймёшь ещё."
    )


def expedition_started(resource: str, pay: int) -> str:
    return (
        f"🚶 Работники потащились за {RESOURCE_EMOJI[resource]} "
        f"{RESOURCE_NAMES[resource].lower()} (−{pay} 🪙).\n"
        f"Вернутся через {balance.EXPEDITION_HOURS} ч — если волки не сожрут."
    )


def expedition_no_gold(pay: int, gold: int) -> str:
    return (
        f"Платить нечем, голодранец: надо {pay} 🪙, у тебя {gold} 🪙. "
        "Бесплатно тут даже не чихают."
    )


def expedition_in_progress(minutes: int) -> str:
    return (
        f"⏳ Ещё пашут. Вернутся через {_fmt_minutes(minutes)} — "
        "раньше не жди и не ной."
    )


def expedition_claimed(claimed: list) -> str:
    """claimed: [(ресурс, количество, удача)]."""
    if not claimed:
        return "Никто пока не вернулся."
    lines = ["🎒 <b>Бригады вернулись с добычей!</b>", ""]
    any_lucky = False
    for resource, amount, lucky in claimed:
        mark = " 🍀" if lucky else ""
        any_lucky = any_lucky or lucky
        lines.append(
            f"{RESOURCE_EMOJI[resource]} {RESOURCE_NAMES[resource]} — +{amount}{mark}")
    if any_lucky:
        lines += ["", "🍀 Кому-то улыбнулась удача — двойная добыча!"]
    return "\n".join(lines)


RESOURCE_INSTRUMENTAL = {
    "wood": "древесиной",
    "grain": "зерном",
    "hops": "хмелем",
    "water": "водой",
    "honey": "мёдом",
    "berries": "ягодами",
    "game": "дичью",
    "ore": "рудой",
    "clay": "глиной",
    "herbs": "травами",
    "salt": "солью",
    "fish": "рыбой",
    "milk": "молоком",
    "stone": "камнем",
}


def expedition_returned(resources: list) -> str:
    """resources: список ключей ресурсов вернувшихся бригад."""
    names = ", ".join(
        f"{RESOURCE_EMOJI.get(r, '📦')} "
        f"{RESOURCE_INSTRUMENTAL.get(r, RESOURCE_NAMES.get(r, r))}"
        for r in resources
    )
    return (
        f"🎒 <b>Бригады вернулись!</b>\n"
        f"С добычей: {names}. Забирай, пока крысы не растащили."
    )


def income_success(r, player=None) -> str:
    from bot.game import logic
    from bot.game import production as prod

    parts = [
        "💰 <b>КАССА</b>",
        "",
        f"«В кассе осело {r.gold} 🪙 пассива»",
        "",
        *_branch("ПАССИВ", [f"🪙 {r.passive} за простой кабака"]),
    ]
    if r.order:
        base = logic.retail_total(r.order)
        total = logic.retail_total(r.order, player)
        items = [
            f"{prod.GOODS[k].emoji} {prod.GOODS[k].name} — {n} × {prod.GOODS[k].price}"
            f" = {n * prod.GOODS[k].price} 🪙"
            for k, n in sorted(r.order.items(), key=lambda kv: -prod.GOODS[kv[0]].price)
        ]
        parts += [
            "",
            *_branch("ГОСТИ ХОТЯТ ВЫКУПИТЬ", items),
        ]
        if total != base:  # активен баф «Бойкая касса»
            parts.append(f"🍺 <i>Баф «Бойкая касса»: {base} → {total} 🪙</i>")
        parts += ["", f"Налить гостям на <b>{total} 🪙</b>?"]
    else:
        parts += ["", "<i>Гостей на твой товар нет — только пассив.</i>"]

    mods = []
    if r.fair:
        mods.append("🎪 Ярмарка — спрос вдвое, куй железо!")
    if r.city_label and r.skim:
        mods.append(f"{r.city_label} — утекло {r.skim} 🪙")
    elif r.city_label:
        mods.append(f"{r.city_label}")
    if r.perk_demand > 1.0:
        mods.append(f"💰 Купеческая протекция — +{round((r.perk_demand - 1) * 100)}% сбыт")
    if r.mood_factor >= 1.02:
        mods.append(f"😀 Город в духе — +{round((r.mood_factor - 1) * 100)}% спрос")
    elif r.mood_factor <= 0.98:
        mods.append(f"😟 Город хмур — −{round((1 - r.mood_factor) * 100)}% спрос")
    if r.season_demand >= 1.4:
        mods.append(f"{r.season_label} — спрос ×{r.season_demand:g}!")
    elif r.season_demand >= 1.02:
        mods.append(f"{r.season_label} — +{round((r.season_demand - 1) * 100)}% спрос")
    elif r.season_demand <= 0.98:
        mods.append(f"{r.season_label} — −{round((1 - r.season_demand) * 100)}% спрос")

    amult = logic.assortment_mult(r.order)
    if r.order and amult > 1.0:
        mods.append(f"🍽 Богатое меню ({len(r.order)} вида) — +{round((amult - 1) * 100)}% выручки")
    from bot.game import worldevent
    fg = worldevent.fashion_good()
    if r.order and fg in (r.order or {}):
        g = prod.GOODS.get(fg)
        mods.append(f"🔥 В моде {g.name if g else fg} — "
                    f"+{round((worldevent.active().good_price - 1) * 100)}% цена")
    if mods:
        parts += ["", *_branch("ОБСТАНОВКА", mods)]
    tail = []
    if r.premium_missed:
        tail.append(f"🍷 Богачи ушли ({r.premium_left}) — не нашлось дорогого пойла, "
                    f"<b>упущено ~{r.premium_missed} 🪙</b>. Держи вино/крепкое "
                    f"(можно докупить на бирже).")
    if r.premium_unsold:
        tail.append("⚠️ Состоятельных мало — дорогое не разбирают")
    if r.spoiled:
        lost = " · ".join(
            f"{prod.GOODS[k].name} −{n}"
            for k, n in sorted(r.spoiled.items(), key=lambda kv: -kv[1])
        )
        tail.append(f"🐀 Погреб переполнен — прокисло: {lost}")
    if tail:
        parts += ["", *tail]
    return "\n".join(parts)


def retail_sold(sold: dict, gold: int, rep: int, skim: int = 0,
                rep_left: int | None = None) -> str:
    from bot.game import production as prod
    items = [
        f"{prod.GOODS[k].emoji} {prod.GOODS[k].name} — {n} × {prod.GOODS[k].price}"
        for k, n in sorted(sold.items(), key=lambda kv: -prod.GOODS[kv[0]].price)
    ]
    parts = [
        "🍺 <b>НАЛИТО ГОСТЯМ!</b>",
        "",
        *_branch("СБЫТ", items),
        "",
        f"🪙 Выручка — +{gold}",
    ]
    if skim:
        parts.append(f"🥷 Утекло на сторону — −{skim}")
    if rep:
        parts.append(f"⭐ +{rep} к репутации за бойкую торговлю")
    if rep_left is not None:   # видно прогресс, даже если +0 за эту продажу
        parts.append(f"📣 До следующей +1 репутации — ещё <b>{rep_left}</b> порций")
    from bot.game import worldevent
    fg = worldevent.fashion_good()
    if fg in (sold or {}):     # модный товар ушёл по премиальной цене
        g = prod.GOODS.get(fg)
        parts.append(f"🔥 {g.name if g else fg} в моде — ушёл с наценкой!")
    return "\n".join(parts)


def retail_held() -> str:
    return ("🤚 Придержал товар — гости разошлись несолоно хлебавши. "
            "Полежит в погребе (только гляди, чтоб не скисло).")


def retail_prompt(want: dict, player=None) -> str:
    from bot.game import logic
    from bot.game import production as prod
    base = logic.retail_total(want)
    total = logic.retail_total(want, player)
    items = [
        f"{prod.GOODS[k].emoji} {prod.GOODS[k].name} — {n} × {prod.GOODS[k].price}"
        f" = {n * prod.GOODS[k].price} 🪙"
        for k, n in sorted(want.items(), key=lambda kv: -prod.GOODS[kv[0]].price)
    ]
    parts = [
        "🍺 <b>ГОСТИ ЖДУТ ЗАКАЗ</b>",
        "",
        *_branch("ХОТЯТ ВЫКУПИТЬ", items),
        "",
    ]
    if total != base:  # активен баф «Бойкая касса»
        parts.append(f"🍺 <i>Баф «Бойкая касса»: {base} → {total} 🪙</i>")
    parts.append(f"Налить гостям на <b>{total} 🪙</b>?")
    return "\n".join(parts)


def _good_name(key: str) -> str:
    from bot.game import production as prod
    g = prod.GOODS.get(key)
    return g.name if g else key


def auction_screen(tavern) -> str:
    """Аукцион: статус активного лота или приглашение выставить товар."""
    from bot.game import auction as auc
    from bot.game import npc
    from bot.game import production as prod

    lot = tavern.auction or None
    if not lot:
        return "\n".join([
            "🔨 <b>АУКЦИОН НЕДОЛИВСКА</b>",
            "",
            "«Выставь товар на торги — и горожане сами набегут перебивать цену. "
            "Кто в духе да при деньгах — отвалит щедро»",
            "",
            "<i>Лот висит 6 часов. Заломишь цену — могут и не взять. "
            "Товар на торгах заморожен.</i>",
        ])
    g = prod.GOODS[lot["good"]]
    left = auc.time_left_minutes(lot)
    top = lot.get("top_bid")
    lines = [
        f"📦 Лот — {lot['qty']} × {g.emoji} {g.name}",
        f"🏷 Резерв — {lot['unit_min']} 🪙/шт",
        f"⏳ Осталось — {_fmt_minutes(left)}",
    ]
    if top:
        lines.append(f"🔝 Ставка — {top} 🪙/шт · {npc.label(lot['top_bidder'])}")
        lines.append(f"🪙 Светит куш — {top * lot['qty']}")
    else:
        lines.append("🤷 Ставок пока нет — ждём покупателей")
    parts = ["🔨 <b>ТОРГИ ИДУТ</b>", "", *_branch("ЛОТ", lines)]
    hist = lot.get("history", [])
    if len(hist) > 1:
        parts += ["", *_branch("СТАВКИ", [
            f"{npc.label(h['npc'])} — {h['unit']} 🪙" for h in reversed(hist)
        ])]
    return "\n".join(parts)


def auction_pick_qty(good: str, stock: int, world) -> str:
    from bot.game import auction as auc
    from bot.game import production as prod
    g = prod.GOODS[good]
    fv = int(round(auc.fair_value(world, good)))
    return "\n".join([
        f"🔨 <b>ВЫСТАВИТЬ: {g.name.upper()}</b>",
        "",
        *_branch("ТОВАР", [
            f"{g.emoji} На складе — {stock} шт",
            f"💰 Рыночная цена ~{fv} 🪙/шт",
        ]),
        "",
        "Сколько штук выставить на торги?",
    ])


def auction_pick_price(good: str, qty: int, world) -> str:
    from bot.game import auction as auc
    from bot.game import production as prod
    g = prod.GOODS[good]
    fv = int(round(auc.fair_value(world, good)))
    return "\n".join([
        f"🔨 <b>ЛОТ: {qty} × {g.name.upper()}</b>",
        "",
        f"💰 Рыночная цена ~{fv} 🪙/шт",
        "",
        "Какую стартовую (резервную) цену поставить?",
        "<i>Чем жаднее — тем выше куш, но и риск, что не возьмут.</i>",
    ])


def auction_settled(res: dict) -> str:
    from bot.game import npc
    from bot.game import production as prod
    g = prod.GOODS[res["good"]]
    if res["sold"]:
        return "\n".join([
            "🔨 <b>ЛОТ УШЁЛ!</b>",
            "",
            f"{npc.label(res['npc'])} забрал лот.",
            "",
            *_branch("СДЕЛКА", [
                f"📦 Продано — {res['qty']} × {g.emoji} {g.name}",
                f"💰 Цена — {res['unit']} 🪙/шт",
                f"🪙 Выручка — +{res['gold']}",
            ]),
        ])
    return "\n".join([
        "🔨 <b>ТОРГИ ОКОНЧЕНЫ</b>",
        "",
        f"«Никто не дал твоей цены за {g.name} — лот снят, "
        f"{res['qty']} шт вернулись в погреб»",
    ])


def trade_offer(offer: dict) -> str:
    want = [
        f"🛢 {_good_name(offer['good'])} — до {offer['qty']} шт",
        f"💰 Рыночная цена ~{int(offer['fv'])} 🪙/шт",
    ]
    mkt = offer.get("mkt", 1.0)
    if mkt <= 0.85:
        want.append(f"📉 Рынок завален — цена просела ({round((1 - mkt) * 100)}%)")
    return "\n".join([
        f"{offer['emoji']} <b>{offer['name'].upper()}</b>",
        f"<i>{offer['intro']}</i>",
        "",
        *_branch("ХОЧЕТ КУПИТЬ", want),
        "",
        "За сколько отдашь штуку, кабатчик?",
    ])


def trade_sold(offer: dict, qty: int, unit: int, gold: int, react: str) -> str:
    return "\n".join([
        f"{offer['emoji']} <i>{react}</i>",
        "",
        "🤝 <b>ПО РУКАМ!</b>",
        "",
        *_branch("СДЕЛКА", [
            f"🛢 Продано — {qty} × {_good_name(offer['good'])}",
            f"💰 Цена — {unit} 🪙/шт",
            f"🪙 Выручка — +{gold}",
        ]),
    ])


def trade_counter(offer: dict, react: str) -> str:
    return "\n".join([
        f"{offer['emoji']} <b>{offer['name'].upper()}</b>",
        "",
        f"<i>{react}</i>",
    ])


def trade_walked(offer: dict, react: str) -> str:
    return (
        f"{offer['emoji']} <b>{offer['name']}</b>\n\n"
        f"<i>{react}</i>\n\nТовар при тебе — поищет другого дурака."
    )


def trade_cancelled() -> str:
    return "Передумал продавать — купец пожал плечами и потопал дальше."


def bourse_news(sells: list, buys: list) -> str:
    """Сводка свежих лотов биржи в чаты (верстка как на главном экране).
    sells/buys: [(good, qty, price)]."""
    from bot.game import production as prod

    def line(good: str, qty: int, price: int) -> str:
        g = prod.GOODS.get(good)
        nm = f"{g.emoji} {g.name}" if g else good
        return f"└ {nm} ×{qty} — по {price}🪙"

    parts = [
        "🪙 <b>БИРЖА НЕДОЛИВСКА</b>",
        "свежий товар на торгу",
        "",
        _HRULE,
    ]
    if sells:
        parts.append("<b>НЕСУТ НА ПРОДАЖУ</b>")
        parts += [line(*s) for s in sells]
    if buys:
        parts.append("<b>СКУПАЮТ НА КОРНЮ</b>")
        parts += [line(*b) for b in buys]
    parts += [
        _HRULE,
        "",
        "<i>Кто проворен — при барыше, кто зевает — глотает пыль.\n"
        "🏪 Рынок → 🛒 Купить · 📥 Заявки</i>",
    ]
    return "\n".join(parts)


def worldevent_announce(ev, good_id: str | None = None) -> str:
    """Анонс мирового события в чаты/личку (трактирный стиль) + последствия.
    Для моды (good_id) — называем товар и премию к его цене."""
    from bot.game import worldevent
    from bot.game import production as prod
    if good_id and ev.good_price != 1.0:
        g = prod.GOODS.get(good_id)
        gname = f"{g.emoji} {g.name}" if g else good_id
        return (f"{ev.emoji} <b>{ev.name.upper()}: {gname.upper()}</b>\n«{ev.blurb}»\n"
                f"📊 <b>спрос на {gname} — цена +{round((ev.good_price - 1) * 100)}% "
                f"и в кабаке, и на бирже</b>")
    return (f"{ev.emoji} <b>{ev.name.upper()}</b>\n«{ev.blurb}»\n"
            f"📊 <b>{worldevent.effect_summary(ev)}</b>")


def market_pulse_announce(cit) -> str:
    """Анонс в чат: горожанин качнул рынок своими делами."""
    good, delta, verb = cit.pulse
    if delta < 0:   # скупка/ажиотаж — товар в цене
        effect = f"📈 {_good_name(good)} в цене — куй железо, сбывай, пока берут!"
    else:           # завал — товар дешевеет
        effect = f"📉 {_good_name(good)} дешевеет — придержи товар до лучших дней."
    return f"{cit.emoji} <b>{escape(cit.name)}</b> {verb}.\n{effect}"


def market_pulse_chron(cit) -> str:
    _good, _delta, verb = cit.pulse
    return f"{cit.name} {verb}."


def _hunter_stats(player):
    from bot.game import combat
    st = combat.player_stats(player)  # снаряга + активные бафы (удача/шкура)
    dmg = balance.BASE_DAMAGE + st["damage"]
    crit = min(balance.HUNT_CRIT_CAP, st["crit"] + st["luck"] // 2)
    return st, dmg, crit, combat


def _hp_bar(cur: int, mx: int) -> str:
    fill = max(0, min(5, round(5 * cur / mx))) if mx else 0
    return "❤" * fill + "▱" * (5 - fill)


def _hp_line(player) -> str:
    """Строка здоровья: текущее/макс + полоска + таймер до полного восстановления."""
    from bot.game import combat
    chp, mx = combat.current_hp(player), combat.max_hp()
    line = f"❤ Здоровье — {chp}/{mx} {_hp_bar(chp, mx)}"
    if chp < mx:
        line += f" · ⏳ до полного {_fmt_minutes(combat.regen_full_minutes(player))}"
    return line


def hunt_menu(player) -> str:
    st, dmg, crit, combat = _hunter_stats(player)
    chp = combat.current_hp(player)
    parts = [
        "🏹 <b>ОХОТА</b>",
        "",
        *_branch("ТВОЙ БОЕЦ", [
            _hp_line(player),
            f"⚔ Урон — {dmg}",
            f"💥 Крит — {crit}%",
            f"🛡 Броня — {st['armor']}",
        ]),
    ]
    ready, mins = combat.hunt_ready(player)
    if not ready:
        parts += ["", f"🩸 Ранен — отлёживаешься, в строй через {_fmt_minutes(mins)}"]
    prey = []
    for e in combat.huntable(getattr(player, "region", None)):   # +зверь своего региона
        wp, _ = combat.forecast(st, e, chp, 120)   # шансы от текущего HP
        tcol, _lbl = combat.threat(wp)
        reg = " 🗺" if e.region else ""             # пометка регионального зверя
        prey.append(f"{tcol} {e.emoji} {e.name}{reg} — ❤{e.hp}")
    parts += ["", *_branch("ЗВЕРЬЁ (цвет — твои шансы)", prey)]
    parts += ["", "<i>Жми на зверя — покажу расклад по твоим статам и добычу.</i>"]
    return "\n".join(parts)


def heal_menu(player) -> str:
    from bot.game import combat
    from bot.game import production as prod
    chp, mx = combat.current_hp(player), combat.max_hp()
    prods = (player.tavern.products if player.tavern else None) or {}
    parts = ["🍖 <b>ПОДЛЕЧИТЬСЯ</b>", "", _hp_line(player), ""]
    avail = [k for k in balance.HEAL_VALUES if prods.get(k, 0) > 0]
    if chp >= mx:
        parts.append("«Сыт и здоров — лечиться незачем.»")
    elif not avail:
        parts.append("«В погребе пусто — нечем подлечиться. Свари жаркое на кухне "
                     "или налей дешёвого эля.»")
    else:
        parts += _branch("ЧЕМ ПОДЛЕЧИТЬСЯ", [
            f"{prod.GOODS[k].emoji} {prod.GOODS[k].name} +{balance.HEAL_VALUES[k]} ❤ "
            f"(в погребе {prods.get(k, 0)})" for k in avail])
        parts += ["", "<i>Жаркое сытнее эля. Что съешь — в погреб не вернётся.</i>"]
    return "\n".join(parts)


# Подсказки-слабости (Фаза 5): что РЕАЛЬНО работает против черты зверя.
_TRAIT_HINT = {
    "venom": "☠ Ядовит — бьёт сквозь броню (она бесполезна). Спасает уворот "
             "(удача) или быстрый занос уроном/критом.",
    "evasive": "💨 Увёртлив — уводит часть твоих ударов. Броня не добьёт его: "
               "нужен высокий урон/крит.",
}


def hunt_detail(player, enemy) -> str:
    st, _dmg, _crit, combat = _hunter_stats(player)
    chp = combat.current_hp(player)
    wp, avg = combat.forecast(st, enemy, chp, 200)
    tcol, lbl = combat.threat(wp)

    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}     # +компоненты (шкура/клык/…)
    nmn = {**RESOURCE_NAMES, **balance.GOODS_NAMES}
    guar, rare = [], []
    for d in enemy.drops:
        if d.res:
            nm = f"{ico.get(d.res, '📦')} {nmn.get(d.res, d.res)}"
            rng_s = f"{d.lo}" if d.lo == d.hi else f"{d.lo}–{d.hi}"
            line = f"{nm} {rng_s}"
        else:
            line = d.label
        (guar if d.chance >= 100 else rare).append((line, d.chance))

    g = [ln for ln, _ in guar] + [f"🪙 Золото {enemy.gold[0]}–{enemy.gold[1]}"]
    if enemy.rep:
        g.append(f"⭐ Репутация +{enemy.rep}")
    odds = [f"{tcol} {lbl}", f"🎯 Победа ~{wp}% (при ❤{chp}/{combat.max_hp()})"]
    if wp > 0:
        odds.append(f"❤ Останется ~{avg}/{combat.max_hp()}")

    parts = [
        f"🏹 <b>{enemy.emoji} {enemy.name.upper()}</b>",
        "",
        f"«{enemy.blurb}»",
        "",
        *_branch("ЗВЕРЬ", [
            f"❤ HP — {enemy.hp}",
            f"⚔ Атака — {enemy.attack}",
            f"🛡 Броня — {enemy.armor}",
        ]),
    ]
    hints = [_TRAIT_HINT[t] for t in getattr(enemy, "traits", ()) if t in _TRAIT_HINT]
    if hints:
        parts += ["", *_branch("⚠ ОСОБЕННОСТЬ", hints)]
    parts += [
        "",
        *_branch("ТВОЙ РАСКЛАД", odds),
        "",
        *_branch("ГАРАНТИРОВАННО", g),
    ]
    if rare:
        parts += ["", *_branch("РЕДКОЕ", [f"{ln} — {c}%" for ln, c in rare])]
    return "\n".join(parts)


def hunt_result(res) -> str:
    e, f = res.enemy, res.fight
    mx = balance.BASE_HP
    ico = {**RESOURCE_EMOJI, **balance.GOODS_EMOJI}      # +компоненты (шкура/клык/…)
    nm = {**RESOURCE_NAMES, **balance.GOODS_NAMES}
    elite_head = ["✨ <b>РЕДКАЯ ДОБЫЧА — повезло!</b>", ""] if res.elite else []
    if f.win:
        loot = res.loot
        body = f"🗡 Уложил за {f.rounds} р."
        if f.crits:
            body += f", {f.crits} критов"
        body += f" · осталось ❤{res.hp_now}/{mx} {_hp_bar(res.hp_now, mx)}"
        detail = [f"🪙 Золото — +{loot['gold']}"]
        for r, q in loot["res"].items():
            detail.append(f"{ico.get(r, '📦')} {nm.get(r, r)} — +{q}")
        if loot["rep"]:
            detail.append(f"⭐ Репутация — +{loot['rep']}")
        for t in loot["trophies"]:
            detail.append(f"🏆 {t}")
        return "\n".join([
            *elite_head,
            f"🏹 <b>{e.emoji} {e.name.upper()} ПОВЕРЖЕН!</b>",
            "", body, "", *_branch("ДОБЫЧА", detail),
        ])
    if f.overwhelmed:
        line = f"{e.name} оказался не по зубам — еле уволок ноги."
    else:
        line = f"{e.name} подмял тебя на {f.rounds}-м раунде."
    tail = [f"🩸 Еле выполз — ❤{res.hp_now}/{mx} {_hp_bar(res.hp_now, mx)}",
            "Отлёживайся — здоровье вернётся со временем."]
    if res.gold_lost:
        tail.append(f"🪙 Обронил в суматохе — −{res.gold_lost}")
    return "\n".join([
        f"🩸 <b>{e.emoji} {e.name.upper()} ОДОЛЕЛ ТЕБЯ</b>",
        "", f"«{line}»", "", *tail,
    ])


def hunt_anim_frames(res) -> list[str]:
    """Кадры анимации боя (нарастающий лог раундов) — последний кадр = итог."""
    e, f = res.enemy, res.fight
    head = f"🏹 <b>СХВАТКА: {e.emoji} {e.name.upper()}</b>"
    frames = [f"{head}\n\n<i>Сходишься вплотную…</i>"]
    acc: list[str] = []
    for rd in (f.log or [])[:4]:
        if rd.get("miss"):
            s = "💨 Промах — зверь увернулся!"
        else:
            s = f"⚔ Бьёшь на {rd['pd']}" + (" 💥 КРИТ!" if rd["crit"] else "")
        if rd["ed"]:
            s += f"\n{e.emoji} в ответ −{rd['ed']}"
        s += f"\n   <i>{e.name} ❤{rd['ehp']} · ты ❤{rd['php']}</i>"
        acc.append(s)
        frames.append(f"{head}\n\n" + "\n\n".join(acc))
    frames.append(hunt_result(res))
    return frames


def loot_drop(flavor: str) -> str:
    return f"👀 <b>{flavor}</b>\n\nКто первый нажмёт — тот и подберёт!"


def loot_claimed(name: str, out: dict, stored: bool = True) -> str:
    name = escape(name)
    if out["kind"] == "resource":
        rn = RESOURCE_NAMES.get(out["res"], out["res"])
        re_ = RESOURCE_EMOJI.get(out["res"], "📦")
        if stored:
            return (f"🤲 <b>{name}</b> подобрал и нашёл там "
                    f"{re_} {rn} ×{out['qty']}! Подфартило.")
        return (f"🤲 <b>{name}</b> нашёл {re_} {rn} ×{out['qty']}, да кабака нет — "
                "добро пропало даром. Заводи свой: /start")
    if out["kind"] == "nothing":
        return f"🤲 <b>{name}</b> подобрал… а там пусто. Показалось, видать. Облом."
    return f"🤲 <b>{name}</b> подобрал… {out['junk']}. Фу-у-у, лучше б мимо прошёл."


def income_empty() -> str:
    return "💤 Касса пуста, как башка завсегдатая. Заглядывай позже."


# Возвращалка: напоминания забывчивому хозяину (3 ступени по сроку простоя).
_IDLE_NUDGE = {
    1: [
        "🍺 Эй, хозяин! Кабак скучает, паутина по углам, половой носом клюёт. "
        "Завалил бы, что ли.",
        "🍺 Пыль на стойке в палец толщиной, бочки сами себя не продадут. "
        "Оторви зад от лавки да загляни.",
        "🍺 Гости стучатся, а хозяина нет. Нехорошо. Возвращайся, лодырь.",
    ],
    2: [
        "🍺 Трое суток ни слуху ни духу! Половой спился с тоски, кот сожрал "
        "всё жаркое. Где тебя носит?",
        "🍺 Конкуренты уже делят твоих гостей, кабатчик. Кабак без хозяина — "
        "что кружка без эля. Возвращайся, пока есть куда.",
        "🍺 Крысы в погребе устроили сходку и выбрали старосту. Ещё чуть — "
        "перепишут таверну на себя.",
    ],
    3: [
        "🍺 НЕДЕЛЯ тебя нет, ирод! Вывеска покосилась, мыши платят за постой, "
        "а староста крыс уже зовётся трактирщиком. Тащи сюда свою пьяную тушу, "
        "пока есть что спасать.",
        "🍺 Все решили, ты помер под забором. Поминки уже накрыли — твоим же "
        "элем. Докажи, что жив — зайди!",
    ],
}


def idle_nudge(tier: int) -> str:
    import random
    return random.choice(_IDLE_NUDGE.get(tier, _IDLE_NUDGE[1]))


def onboard_nudge(referred: bool) -> str:
    """Дожим онбординга: завёл аккаунт, но кабак не открыл."""
    base = ("🍻 <b>Кабак так и не открылся</b>\n\n"
            "Ты заглянул в Недоливск, но вывеску не повесил. А зря — минута дела, "
            "и ты в игре: свои работяги, варка эля, торговля, рейды на боссов.")
    if referred:
        base += ("\n\nК тому же тебя позвал друг — заведёшь кабак, и вам обоим "
                 "капнут подъёмные.")
    return base


# Утренний пуш «бонус готов» (10:00 МСК).
_BONUS_PUSH = [
    "🍺 Утро, хозяин! Опохмел подъехал — забери бонус дня, пока не выветрился.",
    "🍺 Колокол пробил десять! Свежий бонус на стойке — хватай, не зевай.",
    "🍺 Новый день — новая халява. Загляни в кабак за бонусом дня!",
    "🍺 Подъём, кабатчик! Бонус дня уже греется у очага — не проспи.",
]


def bonus_ready_push() -> str:
    import random
    return random.choice(_BONUS_PUSH)


def _reward_str(reward: dict) -> str:
    ico = {"gold": "🪙", **RESOURCE_EMOJI}
    return " ".join(f"{ico.get(r, r)}{a}" for r, a in reward.items())


def starter_chest(chest: dict) -> str:
    return (
        "📦 <b>СУНДУК НОВОСЁЛА</b>\n"
        f"Город подкинул на обзаведение: {_reward_str(chest)}.\n"
        "Трать с умом — на бригады да первую перестройку."
    )


def newbie_screen(player, tavern) -> str:
    from bot.game import newbie
    lines = [
        "📜 <b>ГРАМОТА НОВОСЁЛА</b>",
        "",
        "«Обживайся, кабатчик — за первые шаги город отсыпет на бедность.»",
        "",
    ]
    for _key, label, reward, done, claimed in newbie.states(player, tavern):
        mark = "✅" if claimed else ("🎁" if done else "⬜")
        lines.append(f"{mark} {label} — {_reward_str(reward)}")
    if newbie.claimable(player, tavern):
        lines += ["", "🎁 <b>Есть готовые награды — жми «Забрать»!</b>"]
    from bot.game import newbie
    perks_on = newbie.perks_active(player)
    head = "ПОБЛАЖКИ — активны" if perks_on else "ПОБЛАЖКИ — выдохлись"
    lines += ["", *_branch(head, [
        "🪙 работники −50% · ⛏ добыча +25% · 🦵 ходки быстрее",
        f"<i>только первые {newbie.NEWBIE_GRACE_DAYS} дней и до ур.3 — "
        "потом сам, кабатчик.</i>",
    ])]
    return "\n".join(lines)


def newbie_claimed(total: dict) -> str:
    if not total:
        return "Пока нечего забирать — выполняй задания грамоты."
    return f"🎁 Получено: {_reward_str(total)}. Так держать, новосёл!"


# ── Городская биржа (P2P) ───────────────────────────────────────────────────
def _good_label(good: str) -> str:
    from bot.game import production as prod
    g = prod.GOODS.get(good)
    return f"{g.emoji} {g.name}" if g else good


def bourse_list(orders, names: dict, page: int, total: int,
                cat: str, side: str) -> str:
    CAT_LABEL = {"all": "Всё", "drink": "Напитки", "food": "Еда"}
    if side == "sell":
        head = "🛒 <b>КУПИТЬ — лоты продажи</b>"
        hint = "Жми на лот, чтобы купить. Товар ляжет в твой погреб."
        empty = "Никто не продаёт. Сам выставь спрос — 📣 «Куплю»."
    else:
        head = "📥 <b>ЗАЯВКИ «КУПЛЮ»</b>"
        hint = "Жми на заявку, чтобы продать ей товар из погреба."
        empty = "Заявок нет. Сам выстави на продажу — 📤."
    lines = [f"{head} · {CAT_LABEL[cat]} · лотов: {total} · стр. {page + 1}", ""]
    if not orders:
        lines.append(f"<i>{empty}</i>")
    for o in orders:
        who = escape(names.get(o.seller_id, "кто-то"))
        verb = "от" if side == "sell" else "хочет"
        lines.append(
            f"{_good_label(o.good)}: {o.qty}шт × {o.unit_price}🪙 "
            f"(= {o.qty * o.unit_price}) · {verb} {who}")
    if orders:
        lines += ["", f"<i>{hint}</i>"]
    return "\n".join(lines)


def bourse_order(order, seller_name: str, player: Player,
                 best_bid: int | None = None) -> str:
    afford = player.gold // order.unit_price if order.unit_price > 0 else 0
    lines = [
        "🛒 <b>ЛОТ ПРОДАЖИ</b>",
        "",
        f"{_good_label(order.good)} — {order.qty} шт по {order.unit_price} 🪙/шт",
        f"Весь лот: <b>{order.qty * order.unit_price} 🪙</b>",
        f"Продавец: {escape(seller_name)}",
    ]
    if best_bid is not None:
        lines.append(f"📈 Спрос на бирже: купят до {best_bid} 🪙/шт")
    lines += [
        "",
        f"🪙 У тебя {player.gold} — хватит на {afford} шт.",
        f"<i>Покупаешь сколько надо. Лимит скупки — {balance.BOURSE_BUY_LIMIT} шт "
        f"одного товара за {balance.BOURSE_BUY_WINDOW_H}ч.</i>",
    ]
    return "\n".join(lines)


def bourse_bid(order, owner_name: str, tavern, best_ask: int | None = None) -> str:
    from bot.game import bourse
    stock = int((tavern.products or {}).get(order.good, 0))
    can = min(order.qty, stock)
    net = bourse.net_to_seller(order.unit_price)
    lines = [
        "📥 <b>ЗАЯВКА «КУПЛЮ»</b>",
        "",
        f"{_good_label(order.good)} — нужно {order.qty} шт по {order.unit_price} 🪙/шт",
        f"Тебе на руки: <b>{net} 🪙/шт</b> "
        f"(после налога {int(balance.BOURSE_SALE_TAX * 100)}%)",
        f"Заявку выставил: {escape(owner_name)}",
    ]
    if best_ask is not None:
        lines.append(f"📉 На бирже продают от {best_ask} 🪙/шт (весь мир)")
    lines += [
        "",
        f"📦 В погребе {_good_label(order.good)}: {stock} → продашь до {can} шт.",
    ]
    return "\n".join(lines)


def bourse_sell_intro(tavern, slots_left: int) -> str:
    return "\n".join([
        "📤 <b>ВЫСТАВИТЬ ПРОДАЖУ</b>",
        "",
        f"Свободных лотов продажи: {slots_left}/{balance.BOURSE_MAX_ORDERS}",
        "",
        "Выбери товар из погреба. Цена — в рыночном коридоре, "
        f"биржа берёт <b>{int(balance.BOURSE_SALE_TAX * 100)}%</b> с продажи.",
        "<i>Товар заморозится в лоте, пока не купят или не снимешь.</i>",
    ])


def bourse_bid_intro(player: Player, slots_left: int) -> str:
    return "\n".join([
        "📣 <b>ВЫСТАВИТЬ ЗАЯВКУ «КУПЛЮ»</b>",
        "",
        f"Свободных заявок: {slots_left}/{balance.BOURSE_MAX_ORDERS}",
        f"🪙 В мошне: {player.gold}",
        "",
        "Выбери товар, кол-во и цену. Золото (кол-во × цена) заморозится "
        "в залог и достанется тому, кто продаст; вернётся при отмене.",
    ])


def bourse_pick_qty(good: str, stock: int) -> str:
    return (f"📤 <b>{_good_label(good)}</b>\n"
            f"В погребе: {stock}\n\nСколько выставить на продажу?")


def bourse_bid_qty(good: str, max_qty: int) -> str:
    return (f"📣 <b>{_good_label(good)}</b>\n"
            f"По карману максимум: {max_qty} шт\n\nСколько хочешь купить?")


def bourse_pick_price(good: str, qty: int, *, buy: bool = False) -> str:
    from bot.game import bourse
    lo, hi = bourse.price_floor(good), bourse.price_ceil(good)
    head = "📣" if buy else "📤"
    return (f"{head} <b>{_good_label(good)}</b> · {qty} шт\n\n"
            f"Ценовой коридор: <b>{lo}–{hi}</b> 🪙/шт "
            "(анти-перекачка). Выбери цену:")


def bourse_prices(board: dict) -> str:
    from bot.game import production as prod
    lines = ["📊 <b>ЦЕНЫ ЕДИНОЙ БИРЖИ</b> (весь мир, живые на момент показа)", ""]
    if not board:
        lines.append("<i>Пока тихо — ни лотов, ни заявок во всём мире. Выстави первым!</i>")
    order = sorted(board, key=lambda g: -(prod.GOODS[g].price if g in prod.GOODS else 0))
    for good in order:
        d = board[good]
        parts = []
        if d.get("ask") is not None:
            parts.append(f"продают от {d['ask']}🪙 ({d['ask_qty']})")
        if d.get("bid") is not None:
            parts.append(f"купят до {d['bid']}🪙 ({d['bid_qty']})")
        lines.append(f"{_good_label(good)}: " + " · ".join(parts))
    lines += ["", "<i>🔄 Обновить — пересчитать. В скобках — сколько штук.</i>"]
    return "\n".join(lines)


def bourse_mine(orders) -> str:
    lines = ["📦 <b>МОИ ЛОТЫ НА БИРЖЕ</b>", ""]
    if not orders:
        lines.append("<i>Активных лотов нет.</i>")
    for o in orders:
        tag = "📤 продаю" if o.side == "sell" else "📣 куплю"
        lines.append(f"{tag}: {_good_label(o.good)} {o.qty}шт × {o.unit_price}🪙")
    if orders:
        lines += ["", "<i>Снимешь: товар (продажа) или залог-золото (куплю) "
                  "вернётся тебе.</i>"]
    return "\n".join(lines)


def bonus_screen(player: Player) -> str:
    """Экран ежедневного бонуса: что выпало, эффект, сколько до сгорания."""
    from bot.game import buff as buffmod

    act = buffmod.active(player)
    if act is not None:  # баф уже крутится
        return "\n".join([
            f"🎁 <b>ОПОХМЕЛ</b> · {act.emoji} {act.name}",
            "",
            f"«{act.desc}»",
            "",
            *_branch("ДЕЙСТВУЕТ", [
                f"⏳ Ещё {_fmt_minutes(buffmod.minutes_left(player))}",
            ]),
            "",
            "<i>Один баф за раз. Новый бонус подвезут завтра.</i>",
        ])
    boon = buffmod.offer(player)
    if boon is None:
        return "\n".join([
            "🎁 <b>ОПОХМЕЛ</b>",
            "",
            "«Сегодня халявы нет — всё уже выпито. Загляни завтра.»",
        ])
    return "\n".join([
        f"🎁 <b>БОНУС ДНЯ</b> · {boon.emoji} {boon.name}",
        "",
        f"«{boon.desc}»",
        "",
        *_branch("УСЛОВИЯ", [
            f"✨ Действует {buffmod.BUFF_HOURS} ч после активации",
            f"🔄 Сброс в 10:00 МСК — через {buffmod.offer_hours_left(player)} ч",
        ]),
        "",
        "<i>Активируй, когда подойдёт момент — и греби больше.</i>",
    ])


def bonus_activated(boon, minutes: int) -> str:
    return (
        f"🍺 <b>Опохмелился!</b> {boon.emoji} «{boon.name}» — {boon.desc}.\n"
        f"Гуляет {_fmt_minutes(minutes)}. Куй железо, пока горячо!"
    )


def bonus_busy(boon, minutes: int) -> str:
    return (
        f"⏳ Уже под бафом «{boon.name}» — ещё {_fmt_minutes(minutes)}. "
        "Дождись конца, потом активируй новый."
    )


def bonus_none() -> str:
    return "🎁 Бонус сгорел или ещё не подвезли. Загляни завтра."


def upgrade_offer(player: Player, tavern: Tavern, cost: dict) -> str:
    new_stats = balance.stats_for_level(tavern.level + 1)
    return "\n".join([
        f"🔨 <b>ПЕРЕСТРОЙКА · ур. {tavern.level + 1}</b>",
        "",
        *_branch("ВЫЛОЖИШЬ", [_cost_line(cost, player)]),  # вся стоимость (с ур.5 — и камень)
        "",
        *_branch("ПОЛУЧИШЬ", [
            f"👥 Вместимость — {tavern.capacity} → {new_stats['capacity']}",
            f"✨ Комфорт — {tavern.comfort} → {new_stats['comfort']}",
            f"💰 Доход — {tavern.income_rate} → {new_stats['income_rate']}/ч",
        ]),
        "",
        "<i>Плотники деньги вперёд берут и сдачу не дают.</i>",
    ])


def upgrade_success(new_level: int) -> str:
    return (
        f"🔨 <b>Готово! Уровень {new_level}.</b>\n"
        f"Соседи завидуют, конкуренты скрипят зубами. "
        f"+{balance.reputation_for_upgrade(new_level)} ⭐ к репутации."
    )


def upgrade_not_enough(cost: dict, player: Player) -> str:
    return (
        "😕 С такими запасами только сортир во дворе пристроить.\n\n"
        f"Надо: {_cost_line(cost, player)}\n\n"
        "Иди работай."
    )


UPGRADE_MAX = (
    "🏆 Выше некуда — твой кабак и так легенда Недоливска. "
    "Теперь главное — не профукать."
)


MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
ZONE_EMOJI = {"north_wilds": "❄️", "green_valleys": "🌾", "red_wastes": "🏜"}


def rating_screen(rows: list, total_gdp: int, total_taverns: int) -> str:
    """rows: [(место, название, имя владельца, уровень, регион, ВВП, репутация)]"""
    lines = [
        "🏆 <b>ДОСКА ПОЧЁТА НЕДОЛИВСКА</b>",
        f"Кабаков в городе: {total_taverns} · "
        f"ВВП города: <b>{total_gdp:,}</b> 🪙".replace(",", " "),
        "",
    ]
    for place, name, owner, level, region, gdp, rep in rows:
        medal = MEDALS.get(place, f"{place}.")
        zone = ZONE_EMOJI.get(region, "")
        gdp_s = f"{gdp:,}".replace(",", " ")
        lines.append(
            f"{medal} <b>{escape(name)}</b> {zone} ур.{level}\n"
            f"      ВВП {gdp_s} 🪙 · ⭐ {rep} · хозяин: {escape(owner)}"
        )
    lines.append("")
    lines.append(
        "Не нашёл себя в списке? Так и запишем: "
        "пьёшь больше, чем зарабатываешь."
    )
    return "\n".join(lines)


def sellers_screen(rows: list, me: int | None = None) -> str:
    """rows: [(Tavern, Player)] — продавцы по объёму проданного на бирже."""
    lines = [
        "🏪 <b>ЛУЧШИЕ КУПЦЫ НЕДОЛИВСКА</b>",
        "<i>Кто больше всех наторговал на бирже</i>",
        "",
    ]
    if not rows:
        lines.append("Торг пока пуст — выставь лот и стань первым купцом города!")
        return "\n".join(lines)
    for i, (t, p) in enumerate(rows, 1):
        medal = MEDALS.get(i, f"{i}.")
        you = " 👈 <b>ты</b>" if me is not None and p.id == me else ""
        lines.append(
            f"{medal} <b>{escape(t.name)}</b> — продано <b>{t.auction_sold}</b> ед."
            f"\n      хозяин: {escape(p.first_name or '—')}{you}"
        )
    lines.append("")
    lines.append("<i>Торгуй на бирже — товар разбирают, а молва о тебе растёт.</i>")
    return "\n".join(lines)


# ── Зазывала (рефералка) ──────────────────────────────────────────────────────
def referral_welcome(gold: int) -> str:
    return (f"🍻 <b>Тебя позвал друг — рады в Недоливске!</b>\n\n"
            f"Лови <b>{gold} золота</b> на обзаведение. Освоишься — зови своих: "
            f"за каждого, кто заведёт кабак, перепадёт и тебе.")


def referral_screen(link: str, invited: int, ref_tier: int) -> str:
    from bot.game import balance
    lines = [
        "🍻 <b>Зазывала</b>",
        "",
        "Зови друзей в Недоливск — в выгоде оба.",
        "",
        ("<blockquote>За каждого, кто заведёт кабак:\n"
         f"• тебе — <b>{balance.REFERRAL_INVITER_GOLD} золота</b> и "
         f"<b>{balance.REFERRAL_INVITER_REP} репутации</b>\n"
         f"• другу — <b>{balance.REFERRAL_INVITEE_GOLD} золота</b> на старт</blockquote>"),
        "",
        f"Приведено друзей: <b>{invited}</b>",
    ]
    if ref_tier < len(balance.REFERRAL_TIERS):
        need, bonus = balance.REFERRAL_TIERS[ref_tier]
        lines.append(f"До бонуса в <b>{bonus} золота</b>: ещё "
                     f"<b>{max(0, need - invited)}</b>")
    else:
        lines.append("Все вехи зазывалы взяты — ты легенда найма.")
    lines += [
        "",
        "Твоя ссылка (нажми, чтобы скопировать):",
        f"<code>{link}</code>",
    ]
    return "\n".join(lines)


def referrers_screen(rows: list, me: int | None = None) -> str:
    """rows: [(Player, count)] — топ по числу приведённых друзей."""
    lines = [
        "🏆 <b>Лучшие зазывалы</b>",
        "<i>Кто привёл больше всего народу</i>",
        "",
    ]
    if not rows:
        lines.append("Пока тихо — стань первым, кто зазовёт друзей в город.")
        return "\n".join(lines)
    for i, (p, n) in enumerate(rows, 1):
        medal = MEDALS.get(i, f"{i}.")
        you = " (это ты)" if me is not None and p.id == me else ""
        lines.append(f"{medal} <b>{escape(p.first_name or '—')}</b> — {n}{you}")
    return "\n".join(lines)


# ── Лавка скупщика ────────────────────────────────────────────────────────────
def _res(res: str) -> str:
    from bot.game import balance as b
    return f"{b.RESOURCE_EMOJI.get(res, '📦')} {b.RESOURCE_NAMES.get(res, res)}"


def shop_screen(player) -> str:
    return (
        "🛒 <b>Лавка скупщика</b>\n"
        "<i>Бродячий торгаш продаёт сырьё втридорога — зато сразу, без бригад "
        "и ожидания.</i>\n\n"
        f"В мошне: <b>{player.gold}</b> золота.\n"
        "Выбери ресурс и добери сколько нужно."
    )


def shop_resource(player, res: str) -> str:
    from bot.game import shop
    have = int((player.inventory or {}).get(res, 0))
    room = shop.buy_room(player, res)
    return (
        f"🛒 <b>{_res(res)}</b> — <b>{shop.price(res)}</b> золота за единицу\n\n"
        f"<blockquote>В запасе: <b>{have}</b>\n"
        f"В мошне: <b>{player.gold}</b> золота\n"
        f"Дневной лимит: ещё <b>{room}</b></blockquote>\n"
        "Сколько берём?"
    )


def shop_bought(player, res: str, qty: int, cost: int) -> str:
    have = int((player.inventory or {}).get(res, 0))
    return (f"🛒 Куплено: <b>{_res(res)} ×{qty}</b> за <b>{cost}</b> золота.\n"
            f"В запасе теперь <b>{have}</b>, в мошне <b>{player.gold}</b>.")


def shop_cant_afford(res: str) -> str:
    return (f"Не тянешь даже одну единицу {_res(res)} — или дневной лимит исчерпан. "
            "Сходи в бой за золотом или дождись бригад.")


def shop_fill_done(spent: int, level: int) -> str:
    return (f"🛒 Докупил недостающее за <b>{spent}</b> золота — и кабак "
            f"поднялся до <b>ур.{level}</b>! Гуляй, хозяин.")


def shop_fill_poor(need: int, gold: int) -> str:
    return (f"На докуп недостающего нужно <b>{need}</b> золота, а у тебя <b>{gold}</b>. "
            "Не хватает даже на скупщика — добудь ещё или потряси бригады.")


# ===== Персонаж и кузница =====

def _item_bonus_line(item) -> str:
    parts = []
    if item.income_pct: parts.append(f"+{item.income_pct}% доход")
    if item.yield_pct: parts.append(f"+{item.yield_pct}% добыча")
    if item.yield_wood_pct: parts.append(f"+{item.yield_wood_pct}% 🪵")
    if item.speed_pct: parts.append(f"−{item.speed_pct}% время вылазки")
    if item.pay_discount_pct: parts.append(f"−{item.pay_discount_pct}% плата")
    if item.damage: parts.append(f"⚔{item.damage}")
    if item.crit: parts.append(f"💥{item.crit}%")
    if item.armor: parts.append(f"🛡{item.armor}")
    if item.luck: parts.append(f"🍀{item.luck}")
    return " · ".join(parts) if parts else "—"


def character_screen(player, craft_line: str = "") -> str:
    from bot.game import items as it

    equipment = getattr(player, "equipment", None) or {}
    stats = it.combat_stats(equipment)
    worn = len(equipment)
    # Эффективные боевые значения — те же, что в бою/охоте (с базой и удачей).
    dmg = balance.BASE_DAMAGE + stats["damage"]
    crit = min(balance.HUNT_CRIT_CAP, stats["crit"] + stats["luck"] // 2)

    parts = [
        f"🧍 <b>{escape(player.first_name.upper())}, ХОЗЯИН КАБАКА</b>",
        "",
        f"«Морда кирпичом, руки в мозолях. Надето {worn}/{len(it.SLOTS)}»",
    ]
    if craft_line:
        parts += ["", craft_line]
    parts += ["", *_branch("БОЕВЫЕ", [
        _hp_line(player),
        f"⚔ Урон — {dmg}",
        f"💥 Крит — {crit}%",
        f"🛡 Броня — {stats['armor']}",
        f"🍀 Удача — {stats['luck']} · вылазка {balance.lucky_chance(stats['luck'])}%",
    ])]
    bonuses = []
    if it.income_multiplier(equipment) > 1:
        bonuses.append(f"+{round((it.income_multiplier(equipment)-1)*100)}% доход")
    ym = it.yield_multiplier(equipment, "grain")
    if ym > 1:
        bonuses.append(f"+{round((ym-1)*100)}% добыча")
    if it.speed_multiplier(equipment) < 1:
        bonuses.append(f"−{round((1-it.speed_multiplier(equipment))*100)}% время вылазок")
    if it.pay_multiplier(equipment) < 1:
        bonuses.append(f"−{round((1-it.pay_multiplier(equipment))*100)}% плата работникам")
    if bonuses:
        parts += ["", *_branch("ХОЗЯЙСТВО", bonuses)]
    parts += ["", "<i>Голый трактирщик — смешной трактирщик. Загляни в кузницу.</i>"]
    return "\n".join(parts)


def forge_screen(player) -> str:
    return "\n".join([
        "⚒ <b>КУЗНИЦА НЕДОЛИВСКА</b>",
        "",
        "«Мастер плюёт на ладони и косится на твоё золото. "
        "Один заказ за раз, деньги вперёд»",
        "",
        *_branch("В МОШНЕ", [
            f"🪙 {player.gold} · 🪵 {inventory.get(player, 'wood')} · "
            f"🌾 {inventory.get(player, 'grain')} · 🌿 {inventory.get(player, 'hops')}",
        ]),
    ])


def _tier_bonus_line(item, tier: int) -> str:
    parts = []
    if item.income_pct: parts.append(f"+{item.income_pct * tier}% доход")
    if item.yield_pct: parts.append(f"+{item.yield_pct * tier}% добыча")
    if item.yield_wood_pct: parts.append(f"+{item.yield_wood_pct * tier}% 🪵")
    if item.speed_pct: parts.append(f"−{item.speed_pct * tier}% время вылазки")
    if item.pay_discount_pct: parts.append(f"−{item.pay_discount_pct * tier}% плата")
    if item.damage: parts.append(f"⚔{item.damage * tier}")
    if item.crit: parts.append(f"💥{item.crit * tier}%")
    if item.armor: parts.append(f"🛡{item.armor * tier}")
    if item.luck: parts.append(f"🍀{item.luck * tier}")
    return " · ".join(parts) if parts else "—"


def forge_item_screen(item, player, cur_tier: int, next_tier: int) -> str:
    from bot.game import items as it

    if cur_tier >= it.TIER_MAX:
        return (
            f"<b>{item.name} {it.TIER_STARS[it.TIER_MAX]}</b> · "
            f"слот: {it.SLOTS[item.slot]}\n"
            f"<i>{item.description}</i>\n\n"
            f"Даёт: {_tier_bonus_line(item, it.TIER_MAX)}\n\n"
            "Мастерская работа. Лучше уже не выкуют — даже не проси."
        )
    c = it.tier_cost(item, next_tier)
    hours = it.tier_hours(item, next_tier)
    head = f"<b>{item.name} {it.TIER_STARS[next_tier]}</b> · слот: {it.SLOTS[item.slot]}"
    if cur_tier > 0:
        head += (
            f"\nПерековка: {it.TIER_STARS[cur_tier]} → {it.TIER_STARS[next_tier]} "
            f"({it.TIER_NAMES[next_tier]})"
        )
    return (
        f"{head}\n"
        f"<i>{item.description}</i>\n\n"
        f"Будет давать: {_tier_bonus_line(item, next_tier)}\n"
        f"Ковать: {hours} ч\n\n"
        f"Цена: {_cost_line(c, player)}"
    )


def craft_started(item, tier: int, hours: int) -> str:
    from bot.game import items as it

    return (
        f"⚒ Мастер забрал плату и взялся за <b>{item.name} "
        f"{it.TIER_STARS[tier]}</b>.\n"
        f"Будет готово через {hours} ч. Не стой над душой."
    )


def craft_not_enough(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"На «{item.name} {it.TIER_STARS[tier]}» у тебя кишка тонка "
        "и мошна пуста. Иди заработай, потом приходи."
    )


def craft_in_progress(minutes: int) -> str:
    return f"⚒ Мастер ещё куёт. Готово через {_fmt_minutes(minutes)}. Не зуди."


def craft_ready_notification(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"⚒ <b>{item.name} {it.TIER_STARS[tier]} готово!</b>\n"
        "Мастер ждёт — забирай, пока не перепродал кому побогаче."
    )


def hunter_recovered_notification() -> str:
    return (
        "🏹 <b>Раны затянулись!</b>\n"
        "Снова в строю — зверьё в лесу заждалось."
    )


def craft_claimed(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"⚒ <b>{item.name} {it.TIER_STARS[tier]}</b> — твоё!\n"
        f"Надето. {_tier_bonus_line(item, tier)}.\n"
        "Носи и не потеряй по пьяни."
    )


# ===== Рейд-босс (глобальный) =====
def _fmt_left_h(ends_at) -> str:
    from datetime import datetime, timezone
    if ends_at is None:
        return ""
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    sec = (ends_at - datetime.now(timezone.utc)).total_seconds()
    if sec <= 0:
        return "вот-вот сбежит"
    h = int(sec // 3600)
    return f"{h} ч" if h else f"{int(sec // 60)} мин"


def _raid_roster_lines(boss, limit: int = 12) -> list[str]:
    """Список записавшихся по именам (для экрана сбора/боя). Пусто — никто ещё.
    Имена экранируем (HTML) и режем длинные; при толпе показываем «и ещё N»."""
    recs = list((boss.contributions or {}).values())
    if not recs:
        return ["<i>— пока никто, будь первым!</i>"]
    names = []
    for r in recs[:limit]:
        nm = escape(str(r.get("name") or "боец"))
        names.append(nm[:24] + "…" if len(nm) > 25 else nm)
    extra = len(recs) - len(names)
    out = ["  • " + n for n in names]
    if extra > 0:
        out.append(f"  • <i>…и ещё {extra}</i>")
    return out


# Тон под каждого босса: (шапка-тревога, вводная строка с именем, боевой клич).
# Тон под каждого босса: (тэглайн — лёгкий курсив под именем, боевой клич).
# Имя/эмодзи берём из спека — звучит ровно один раз, без капс-дубля.
_RAID_FLAVOR: dict[str, tuple[str, str]] = {
    "rat_king": (
        "Опять эта тварь из подпола.",
        "Налетай всем кабаком, пока гадина кассу не сожрала. Кто по углам "
        "прятался — тот и без сыра.",
    ),
    "bog_troll": (
        "С болот потянуло смрадом…",
        "Вставайте стеной — поодиночке эта груда втопчет в тину. Только всем "
        "миром свалим.",
    ),
    "dragon": (
        "Небо почернело — он проснулся.",
        "Все до единого — в бой. Завтра либо пьём за победу, либо наливать "
        "будет некому.",
    ),
}


def _raid_flavor(boss_key: str) -> tuple[str, str]:
    return _RAID_FLAVOR.get(boss_key, (
        "На Недоливск идёт беда.",
        "Жми «Присоединиться» — бьют только записавшиеся.",
    ))


def _raid_loot_box(boss_key: str) -> str:
    """Сводка добычи аккуратным списком (блок-цитата) + честный % на снарягу."""
    from bot.game import raid
    pct = raid.gear_drop_pct(boss_key)
    return ("<blockquote>Добыча с туши:\n"
            "• золото — поровну всем, кто бил\n"
            "• трофей — одному случайному из них\n"
            f"• снаряга — шанс ~{pct:g}% (иначе ресурсы)</blockquote>")


def raid_gather_screen(boss) -> str:
    """Фаза сбора: тон под босса + правила добычи + кто записался (поимённо)."""
    from bot.game import raid
    spec = raid.BOSSES.get(boss.boss_key)
    if spec is None:
        return "⚔️ Рейд-босс приближается"
    tagline, cta = _raid_flavor(boss.boss_key)
    return "\n".join([
        f"{spec.emoji} <b>{spec.name}</b>",
        f"<i>{tagline}</i>",
        "",
        f"<blockquote expandable>{escape(spec.blurb)}</blockquote>",
        "",
        f"До битвы: <b>{_fmt_left_h(boss.gather_until)}</b> · "
        f"в строю: <b>{raid.registered_count(boss)}</b>",
        *_raid_roster_lines(boss),
        "",
        _raid_loot_box(boss.boss_key),
        "",
        "Награду получает только тот, кто реально бил.",
        "",
        f"<i>{cta}</i>",
    ])


def raid_push_dm(boss) -> str:
    """Пуш-анонс в личку при старте сбора (живой экран — кнопкой в меню таверны)."""
    from bot.game import raid
    spec = raid.BOSSES.get(boss.boss_key)
    if spec is None:
        return "⚔️ Рейд-босс приближается — открой кабак!"
    tagline, _cta = _raid_flavor(boss.boss_key)
    pct = raid.gear_drop_pct(boss.boss_key)
    return (f"{spec.emoji} <b>{spec.name}</b>\n"
            f"<i>{tagline}</i>\n\n"
            "Идёт сбор (~20 мин). Открой кабак и жми "
            "<b>«⚔️ РЕЙД-БОСС — В БОЙ!»</b> в меню.\n\n"
            f"Золото — поровну всем, кто бил; трофей — одному с туши "
            f"(снаряга редка, ~{pct:g}%).")


def raid_fight_ping() -> str:
    return ("⚔️ <b>ОН ЗДЕСЬ — босс дошёл, пора БИТЬ!</b> Лети в чат, где собирались, "
            "и долби «Бить» без передышки. Кто в деле — тот и в доле: золото меж "
            "бойцов, а кому-то одному с туши падёт легендарный трофей. Не отсиживайся!")


def raid_no_show(boss) -> str:
    from bot.game import raid
    spec = raid.BOSSES.get(boss.boss_key)
    name = spec.name if spec else "Босс"
    return (f"{spec.emoji if spec else '⚔️'} <b>{name} не дождался.</b>\n"
            "Ни одна душа не вышла на бой — тварь презрительно фыркнула и уползла. "
            "Позорище на весь Недоливск.")


def raid_screen(boss) -> str:
    """Сообщение рейд-босса в чате: HP-бар, бойцы, время. boss — строка RaidBoss."""
    from bot.game import raid
    spec = raid.BOSSES.get(boss.boss_key)
    if spec is None:
        return "⚔️ Рейд-босс"
    fighters = len(boss.contributions or {})
    pct = round(100 * max(0, boss.hp) / boss.max_hp) if boss.max_hp else 0
    stun = raid.stun_left(boss)
    status = (f"😵 <b>РЁВ!</b> Босс оглушил — удар на паузе ~{stun // 60 + 1} мин"
              if stun > 0 else None)
    return "\n".join([
        f"{spec.emoji} <b>{spec.name}</b>",
        "<i>Рубилово — добиваем.</i>",
        "",
        f"<blockquote expandable>{escape(spec.blurb)}</blockquote>",
        "",
        f"{raid.hp_bar(boss.hp, boss.max_hp)}  {pct}%",
        f"HP: <b>{max(0, boss.hp)} / {boss.max_hp}</b> · броня <b>{spec.armor}</b>",
        f"в деле: <b>{fighters}</b> · уйдёт через <b>{_fmt_left_h(boss.ends_at)}</b>",
        *([status] if status else []),
        "",
        _raid_loot_box(boss.boss_key),
        "",
        "<i>Лупи по «Бить» — дожимаем. Толстая шкура гасит удар, "
        "а простой тварь лечит.</i>",
    ])


def raid_hit_toast(dmg: int, crit: bool, hp: int, max_hp: int, soaked: int = 0) -> str:
    head = f"💥 КРИТ! −{dmg} HP" if crit else f"🗡 −{dmg} HP"
    soak = f" (🛡 −{soaked} в броню)" if soaked > 0 else ""
    return f"{head}{soak} · у босса осталось {max(0, hp)}/{max_hp}"


def raid_dead(boss, top: list, winner_name: str | None, drop_line: str) -> str:
    """top: [(имя, урон)] лидеры; winner_name/drop_line — кому и что выпало."""
    from bot.game import raid
    spec = raid.BOSSES.get(boss.boss_key)
    name = spec.name if spec else "Босс"
    emoji = spec.emoji if spec else "⚔️"
    lines = [f"💀{emoji} <b>{name.upper()} ПОВЕРЖЕН!</b>",
             "", "Всем миром завалили зверюгу — кабаки гудят! Кто рубился:"]
    if top:
        lines += [f"  ⚔️ {escape(n)} — {d} урона" for n, d in top[:5]]
    lines.append("")
    lines.append("💰 Золото — <b>поровну на всех</b>, кто махал. Гляньте мошну.")
    if winner_name and drop_line:
        lines.append(f"🎁 Легендарный трофей урвал <b>{escape(winner_name)}</b>: {drop_line}")
    return "\n".join(lines)


def raid_expired(boss) -> str:
    from bot.game import raid
    spec = raid.BOSSES.get(boss.boss_key)
    name = spec.name if spec else "Босс"
    emoji = spec.emoji if spec else "⚔️"
    return (f"{emoji} <b>{name} ушёл.</b>\n"
            "Провозились — тварь огрызнулась и уползла зализывать раны, унеся всю "
            "добычу. В другой раз шевелитесь живее, мямли.")
