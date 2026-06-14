"""Все игровые тексты в одном месте. Тон — жёсткий трактирный."""

import random
from html import escape

from bot.db.models import Player, Tavern
from bot.game import balance, inventory, logic
from bot.game import world as wld
from bot.game.balance import RESOURCE_EMOJI, RESOURCE_NAMES

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
    "<code>гг кузница</code> — снаряга\n\n"
    "🏰 <b>Живой город</b>\n"
    "• <code>гг город</code> — расклад фракций · <code>гг хроника</code> — летопись\n"
    "• <code>гг репутация</code> — кто как к тебе относится + плюшки\n\n"
    "🗺 <b>Мир</b>\n"
    "• <code>гг карта</code> — карта · <code>гг топ</code> — рейтинг\n"
    "• <code>гг правила</code> — как играть · <code>гг помощь</code> — этот хаб\n\n"
    "В личке: <code>/start</code> — кабак, <code>/help</code> — правила.\n"
    "<i>Чужую панель не лапай — жмёт только хозяин.</i>"
)

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
)

RULES = (
    "🍺 <b>НЕДОЛИВСК — КАК ПОДНЯТЬ КАБАК</b>\n"
    "<blockquote>Твоя задача — из вонючей наливайки сделать богатейший кабак "
    "округи. Чем больше оборот, тем выше ты в рейтинге «гг топ» (меряемся по "
    "ВВП — деньгам, что прошли через таверну).</blockquote>\n\n"

    "<b>⛏ 1. Добыча сырья — бригады</b>\n"
    "Всё начинается с сырья. Жми «Отправить бригады» и шли работяг на вылазку "
    "за деревом, зерном, хмелем, мёдом, ягодой и прочим. За отправку платишь "
    "золотом, а через время бригада вернётся с добычей — её надо «Забрать» на "
    "склад.\n"
    "<i>Чем выше уровень таверны, тем больше бригад уходит разом.</i>\n\n"

    "<b>🏗 2. Производство — пристройки</b>\n"
    "Сырьё само по себе не продать — его надо переработать. Строишь пристройки "
    "(раздел «Пристройки»), и они делают товар:\n"
    "<code>зерно → солод</code> — Мельница\n"
    "<code>солод + хмель → эль</code> — Пивоварня\n"
    "<code>мёд → медовуха / сбитень</code> — Медоварня\n"
    "<code>припасы → жаркое</code> — Кухня\n"
    "<code>ягоды → вино</code> — Винодельня\n"
    "<i>Часть пристроек открывается, когда поднимешь репутацию.</i>\n\n"

    "<b>🍺 3. Варка и погреб</b>\n"
    "В пристройке запускаешь партию, ждёшь готовности (придёт уведомление) и "
    "разливаешь товар в погреб. Эль можно не разливать сразу, а поставить на "
    "<u>выдержку</u> — есть шанс поднять ярус <code>★ → ★★★</code> (дороже и "
    "престижнее), но партия может и скиснуть. Риск.\n\n"

    "<b>💰 4. Доход — где деньги</b>\n"
    "Кнопка «Собрать доход» приносит золото из двух источников:\n"
    "• <u>пассив</u> — таверна капает понемногу сама;\n"
    "• <u>сбыт</u> — гости раскупают товар из погреба.\n"
    "Гости разные: <u>состоятельные</u> берут что подороже, <u>пьянь</u> — что "
    "подешевле, а <u>голод</u> разбирает еду. Чем больше вместимость и "
    "репутация — тем больше гостей и выше доля богатеев, а значит и выручка.\n\n"

    "<b>⭐ 5. Репутация и уровень</b>\n"
    "Репутация растёт, когда продаёшь товар. Она открывает новые пристройки и "
    "приводит богатую публику. Кнопка «Улучшить таверну» поднимает уровень: "
    "тратишь сырьё, но получаешь больше вместимости, комфорта, пассивного "
    "дохода и бригад.\n\n"

    "<b>⚒ 6. Кузница и снаряжение</b>\n"
    "У мастера в кузнице заказываешь снаряжение: шапку, броню, сапоги, пояс, "
    "суму, оружие, амулет. Надетые вещи ускоряют вылазки и увеличивают добычу, "
    "доход и удачу. Повторный заказ той же вещи поднимает её ярус.\n"
    "<i>С удачей бывают <u>счастливые вылазки</u> — добыча кратно жирнее.</i>\n\n"

    "<b>🎪 7. Ярмарка</b>\n"
    "Раз в день в город съезжаются купцы — и спрос на выпивку и еду взлетает "
    "<code>×2</code> на пару часов. В чат заранее падает анонс: успей набить "
    "погреб товаром, чтобы продать втридорога.\n\n"

    "<blockquote>📍 Где играть: в личке с ботом — кнопками; в общем чате — "
    "словом «гг» (полный список команд: «гг помощь»). Когда что-то готово, "
    "уведомление с кнопкой «Забрать» придёт прямо в чат.</blockquote>\n"
    "<tg-spoiler>P.S. Трезвым тут делать нечего.</tg-spoiler>"
)

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

    st = player.story or {}
    lines = ["👥 <b>Горожане Недоливска</b>", ""]

    known = [(nid, v) for nid, v in st.get("npc_rel", {}).items() if v != 0]
    if known:
        lines.append("<b>Как к тебе относятся:</b>")
        for nid, v in sorted(known, key=lambda x: -x[1]):
            lines.append(f"{npc.label(nid)} — {_rel_label(v)}")
    else:
        lines.append("Тебя тут пока не знают. Поживёшь — приметят.")

    facs = [(f, v) for f, v in st.get("faction", {}).items() if v != 0]
    if facs:
        lines += ["", "🏛 <b>Фракции:</b>"]
        for f, v in sorted(facs, key=lambda x: -x[1]):
            lines.append(f"{factions.name(f)} — {_faction_label(v)}")

    from bot.game import perks
    active = perks.active_perks(player)
    if active:
        lines += ["", "🎁 <b>Привилегии:</b>"]
        lines += active
    return "\n".join(lines)


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

    lines = ["🏛 <b>Недоливск сегодня</b>", ""]
    lines.append(f"Настроение: <b>{_mood_label(citymod.mood_value(city))}</b>")
    lines.append("")
    sit = citymod.current(city)
    if sit is not None:
        lines.append(f"{sit.emoji} <b>{sit.label}</b> — в самом разгаре.")
        lines.append("")
    fp = {f: v for f, v in (city.faction_power or {}).items() if v}
    if fp:
        lines.append("<b>Расклад сил:</b>")
        for f, v in sorted(fp.items(), key=lambda x: -x[1]):
            lines.append(f"{factions.name(f)}: {_power_bar(v)} {v}")
        lines.append("")
        lines.append("<i>Кто заберёт власть — решают ваши дела в городе.</i>")
    else:
        lines.append("Тишь да гладь — фракции дремлют. Пока.")
    return "\n".join(lines)


def chronicle_screen(entries: list[str]) -> str:
    """Летопись города — лента заметных событий."""
    if not entries:
        return (
            "📜 <b>Хроники Недоливска</b>\n\n"
            "Летопись чиста, как совесть младенца. Пока тут не стряслось "
            "ничего, достойного пера."
        )
    # Экран персонажа — фото; подпись ≤1024, поэтому строки подрезаем.
    body = "\n".join(f"• {e[:90]}" for e in entries[:10])
    return f"📜 <b>Хроники Недоливска</b>\n\n{body}"


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


def season_announce(s) -> str:
    """Анонс смены сезона в чат."""
    return (
        f"{s.emoji} <b>{s.name.upper()} ПРИШЛА В НЕДОЛИВСК</b>\n\n"
        f"{s.blurb[0].upper()}{s.blurb[1:]}.\n"
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
    """🪙/🪵/… N ✅/❌ — по содержимому словаря стоимости."""
    emoji = {"gold": "🪙", **RESOURCE_EMOJI}
    parts = []
    for key, need in cost.items():
        if not need:
            continue
        have = player.gold if key == "gold" else inventory.get(player, key)
        mark = "✅" if have >= need else "❌"
        parts.append(f"{emoji.get(key, key)} {need} {mark}")
    return " · ".join(parts)


def buildings_screen(player: Player, tavern: Tavern) -> str:
    from bot.game import buildings as bld

    lines = [
        "🏗 <b>Пристройки</b>",
        "",
        "<blockquote>Каждая открывает своё производство. "
        "Деньги и сырьё — вперёд.</blockquote>",
        "",
    ]
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
        lines.append(f"{b.emoji} <b>{b.name}</b> — {status}")
    return "\n".join(lines)


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
        f"🏗 <b>{building.name}</b> достроена! {building.description}\n"
        "Загляни в Пристройки — пора пускать в дело."
    )


# ===== Производство =====

def production_screen(building, player: Player, tavern: Tavern) -> str:
    from bot.game import production as prod

    head = f"{building.emoji} <b>{building.name}</b>\n<i>{building.description}</i>\n"
    if building.id == "mill":
        malt = inventory.get(player, "malt")
        level = tavern.level
        cin = prod.mill_inputs(level)
        out = prod.mill_output(level)
        state, minutes = prod.state(tavern, "mill")
        if state == "active":
            status = f"⏳ Мелется — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🌱 Солод готов — забирай!"
        else:
            status = "😴 Жернова простаивают."
        m_emoji = balance.GOODS_EMOJI["malt"]
        m_name = balance.GOODS_NAMES["malt"]
        g_emoji = RESOURCE_EMOJI["grain"]
        return (
            head +
            f"\n{m_emoji} {m_name} на складе: {malt}\n"
            f"{status}\n\n"
            f"Помол (ур. {level}): {g_emoji} {cin['grain']} → {m_emoji} {out} "
            f"{m_name.lower()}, {prod.MILL_MINUTES} мин\n"
            f"В закромах: {g_emoji} {inventory.get(player, 'grain')}"
        )
    if building.id == "brewery":
        level = tavern.level
        prods = tavern.products or {}
        stock = " · ".join(
            f"{prod.ALE_STARS[t]} {prods.get(f'ale{t}', 0)}" for t in (1, 2, 3)
        )
        phase, minutes = prod.brew_phase(tavern)
        bt = int(tavern.production["brewery"]["tier"]) if phase != "empty" else 0
        if phase == "fermenting":
            status = f"⏳ Бродит {prod.ALE_STARS[bt]} — ещё {_fmt_minutes(minutes)}."
        elif phase == "ready":
            extra = " или выдержи (риск +ярус)" if bt < 3 else ""
            status = f"🍺 {prod.ALE_STARS[bt]} готов — разливай{extra}!"
        elif phase == "aging":
            status = (
                f"🛢 Выдержка {prod.ALE_STARS[bt]} → {prod.ALE_STARS[min(3, bt+1)]}? "
                f"— ещё {_fmt_minutes(minutes)}."
            )
        elif phase == "ripe":
            status = (
                f"⏰ Выдержка дошла! Разливай в течение {_fmt_minutes(minutes)} — "
                "иначе перекиснет."
            )
        elif phase == "overripe":
            status = "⚠️ Перекисает! Разливай немедля — ярус упадёт."
        else:
            status = "😴 Чаны пусты. Выбери, что варить."
        inv = lambda r: inventory.get(player, r)  # noqa: E731
        return (
            head +
            f"\n🛢 Погреб: {stock}\n{status}\n\n"
            f"Рецепты (ур. {level}, выход {12 * level} кружек):\n"
            f"★ {8*level}🌱 {5*level}🌿 {6*level}💧 — 4 ч\n"
            f"★★ то же + {6*level}🍯 — 8 ч\n"
            f"★★★ то же + {12*level}🍯 — 12 ч\n"
            f"Есть: 🌱{inv('malt')} 🌿{inv('hops')} 💧{inv('water')} 🍯{inv('honey')}"
        )
    if building.id == "meadery":
        level = tavern.level
        prods = tavern.products or {}
        stock = f"🍶 {prods.get('mead', 0)} · 🌿 {prods.get('sbiten', 0)}"
        state, minutes = prod.state(tavern, "meadery")
        if state == "active":
            rc = tavern.production["meadery"].get("recipe", "mead")
            status = f"⏳ Готовится {prod.DRINKS[rc].name} — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🍶 Готово — разливай в погреб!"
        else:
            status = "😴 Котлы остыли. Выбери, что варить."
        m = prod.meadery_inputs("mead", level)
        s = prod.meadery_inputs("sbiten", level)
        return (
            head +
            f"\n🛢 Погреб: {stock}\n{status}\n\n"
            f"Рецепты (ур. {level}):\n"
            f"🍶 Медовуха: 🍯 {m['honey']} 💧 {m['water']} — {prod.meadery_hours('mead')} ч\n"
            f"🌿 Сбитень: 🍯 {s['honey']} 🌶 {s['herbs']} 💧 {s['water']} — "
            f"{prod.meadery_hours('sbiten')} ч\n"
            f"Есть: 🍯 {inventory.get(player, 'honey')} · 🌶 {inventory.get(player, 'herbs')} "
            f"· 💧 {inventory.get(player, 'water')}\n"
            "<i>Берут состоятельные — репутация решает.</i>"
        )
    if building.id == "kitchen":
        level = tavern.level
        food = (tavern.products or {}).get("roast", 0)
        cin = prod.kitchen_inputs("roast", level)
        out = prod.kitchen_output("roast", level)
        state, minutes = prod.state(tavern, "kitchen")
        if state == "active":
            status = f"⏳ На вертеле — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🍖 Жаркое готово — в кладовую!"
        else:
            status = "😴 Очаг остыл. Поставь готовить."
        return (
            head +
            f"\n🍖 Жаркое в кладовой: {food}\n{status}\n\n"
            f"Рецепт (ур. {level}): 🥩 {cin['game']} 🌾 {cin['grain']} 🌶 {cin['herbs']} → "
            f"🍖 {out}, {prod.kitchen_hours('roast')} ч\n"
            f"Есть: 🥩 {inventory.get(player, 'game')} · 🌾 {inventory.get(player, 'grain')} "
            f"· 🌶 {inventory.get(player, 'herbs')}\n"
            "<i>Сытые гости платят за еду сверх выпивки (свой спрос).</i>"
        )
    if building.id == "winery":
        level = tavern.level
        wine = (tavern.products or {}).get("wine", 0)
        cin = prod.winery_inputs("wine", level)
        out = prod.winery_output("wine", level)
        state, minutes = prod.state(tavern, "winery")
        if state == "active":
            status = f"⏳ Бродит — ещё {_fmt_minutes(minutes)}."
        elif state == "ready":
            status = "🍷 Вино готово — разливай в погреб!"
        else:
            status = "😴 Бочки пусты. Поставь вино."
        return (
            head +
            f"\n🍷 Вино в погребе: {wine}\n{status}\n\n"
            f"Рецепт (ур. {level}): 🍒 {cin['berries']} 🍯 {cin['honey']} 💧 {cin['water']} → "
            f"🍷 {out}, {prod.winery_hours('wine')} ч\n"
            f"Есть: 🍒 {inventory.get(player, 'berries')} · 🍯 {inventory.get(player, 'honey')} "
            f"· 💧 {inventory.get(player, 'water')}\n"
            "<i>Самый дорогой напиток — берут только богачи (высокая репутация).</i>"
        )
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
        f"{d.emoji} <b>{d.name} готов(а)!</b> Разлей в погреб — "
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
    meadery_name = (
        "Сбитень" if (p.get("meadery") or {}).get("recipe") == "sbiten"
        else "Медовуха")
    simple = [
        ("mill", "🌱", "Солод", "мелется"),
        ("meadery", "🍶", meadery_name, "зреет"),
        ("kitchen", "🍖", "Жаркое", "готовится"),
        ("winery", "🍷", "Вино", "бродит"),
    ]
    for bid, emoji, name, verb in simple:
        if bid not in p:
            continue
        s, m = prod.state(tavern, bid)
        if s == "active":
            out.append(f"{emoji} {name} {verb} — {_fmt_minutes(m)}")
        elif s == "ready":
            out.append(f"{emoji} {name} готово — забирай!")
    return out


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


def _storage_line(player: Player) -> str:
    inv = player.inventory or {}
    parts = [f"{RESOURCE_EMOJI[r]} {inv[r]}"
             for r in balance.RESOURCES if inv.get(r, 0) > 0]
    return " · ".join(parts[:6]) if parts else "пусто"


def _upgrade_pct(player: Player, tavern: Tavern) -> int | None:
    if tavern.level >= balance.MAX_LEVEL:
        return None
    cost = balance.upgrade_cost(tavern.level)
    pcts = []
    for k in ("gold", "wood", "grain", "hops"):
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
    from bot.game import city as citymod
    from bot.game import items as it
    from bot.game import season as seasonmod

    chat_id = getattr(player, "chat_id", None)
    region = balance.REGIONS.get(player.region, player.region)
    flavor = _flavor_line(player, tavern, chat_id, seasonmod, citymod)

    # СЕЙЧАС — активные дела
    now_lines = []
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
    now_lines += _production_lines(tavern)
    bl = _build_line(player)
    if bl:
        now_lines.append(bl)
    pct = _upgrade_pct(player, tavern)
    now_lines.append(f"🔨 Перестройка — {pct}%" if pct is not None
                     else "🏆 Выше строить некуда")

    eq = getattr(player, "equipment", None) or {}
    luck_pct = balance.lucky_chance(it.combat_stats(eq)["luck"])

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
        *_branch("ДЕРЕВНЯ", [
            f"👥 Места — {tavern.capacity}",
            f"✨ Уют — {tavern.comfort}",
            f"🍀 Удача — {luck_pct}%",
            f"🎒 Снаряга — {len(eq)}/{len(it.SLOTS)}",
        ]),
        "",
        *_branch("СКЛАД", [
            _storage_line(player),
            f"🛢 Погреб — {_cellar_line(tavern)}",
        ]),
        "",
        *_branch("МИР", _world_lines(chat_id, seasonmod, citymod)),
    ]
    return "\n".join(parts)


def _upgrade_need_block(player: Player, tavern: Tavern) -> list[str]:
    """Блок «до перестройки» — список строк с галочками."""
    if tavern.level >= balance.MAX_LEVEL:
        return ["🏆 Выше строить некуда — разве что до небес."]
    cost = balance.upgrade_cost(tavern.level)
    emoji = {"gold": "🪙", **RESOURCE_EMOJI}
    out = [f"<b>🔨 До перестройки (ур. {tavern.level + 1})</b>"]
    for key in ("gold", "wood", "grain", "hops"):
        have = player.gold if key == "gold" else inventory.get(player, key)
        mark = "✅" if have >= cost[key] else "❌"
        out.append(f"{emoji[key]} {have} / {cost[key]} {mark}")
    return out


def warehouse_screen(player: Player, tavern: Tavern) -> str:
    lines = [
        f"📦 <b>Склад «{escape(tavern.name)}»</b>",
        "",
        "<blockquote>Темно, пыльно, по углам шуршат крысы. "
        "Вот что ещё не растащили.</blockquote>",
        "",
        f"🪙 <b>Золото — {player.gold}</b>",
        "",
        "<b>📥 Запасы</b>",
    ]
    for res in balance.RESOURCES:
        lines.append(
            f"{RESOURCE_EMOJI[res]} {RESOURCE_NAMES[res]} — {inventory.get(player, res)}"
        )
    lines.append("")
    lines += _upgrade_need_block(player, tavern)
    return "\n".join(lines)


def storehouse_caption(player: Player, tavern: Tavern) -> str:
    """Короткая подпись к складской ведомости (ресурсы — на самой картинке)."""
    lines = [
        f"📦 <b>Складская ведомость «{escape(tavern.name)}»</b>",
        "",
        f"🪙 <b>Золото — {player.gold}</b>",
        "",
    ]
    lines += _upgrade_need_block(player, tavern)
    return "\n".join(lines)


def expedition_menu(player: Player) -> str:
    tavern = player.tavern
    level = tavern.level if tavern else 1
    pay = balance.worker_pay(level)
    c = logic.expedition_counts(player, tavern)
    return (
        "⛏ <b>Бригады работников</b>\n\n"
        f"<blockquote>Свободно {c.free}/{c.total} · в пути {c.out} · "
        f"вернулись {c.ready}</blockquote>\n\n"
        f"Ходка — {balance.EXPEDITION_HOURS} ч, плата {pay} 🪙 за бригаду вперёд.\n"
        "<i>Гони сразу несколько — кто за чем.</i>"
    )


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
}


def expedition_returned(resources: list) -> str:
    """resources: список ключей ресурсов вернувшихся бригад."""
    names = ", ".join(
        f"{RESOURCE_EMOJI[r]} {RESOURCE_INSTRUMENTAL[r]}" for r in resources
    )
    return (
        f"🔔 Бригады вернулись с {names}!\n"
        "Забирай быстрее, пока крысы не растащили, а пьянь не спёрла."
    )


def income_success(r) -> str:
    from bot.game import production as prod

    lines = [
        "💰 <b>Касса</b>",
        "",
        f"<blockquote>В кассе осело <b>{r.gold} 🪙</b></blockquote>",
        "",
    ]
    if r.sales > 0:
        parts = [
            f"{prod.GOODS[k].name} {n}"
            for k, n in sorted(r.sold.items(), key=lambda kv: -prod.GOODS[kv[0]].price)
        ]
        lines.append(f"Пассив {r.passive} + сбыт {r.sales}")
        lines.append(f"🍺 Раскуплено: {' · '.join(parts)}")
    else:
        lines.append("Сбыта нет — только пассивный доход с заведения.")
    if r.fair:
        lines.append("🎪 Ярмарка! Гости валом — спрос вдвое. Куй железо!")
    if r.city_label and r.skim:
        lines.append(
            f"{r.city_label}: с выручки утекло <b>{r.skim} 🪙</b> "
            f"(в кассе осталось {r.gold - r.skim})."
        )
    elif r.city_label:
        lines.append(f"{r.city_label} — сказывается на сбыте в городе.")
    if r.perk_demand > 1.0:
        lines.append(
            f"💰 Купеческая протекция: +{round((r.perk_demand - 1) * 100)}% к сбыту."
        )
    if r.mood_factor >= 1.02:
        lines.append(
            f"😀 Город в приподнятом духе — спрос выше на "
            f"{round((r.mood_factor - 1) * 100)}%."
        )
    elif r.mood_factor <= 0.98:
        lines.append(
            f"😟 Город хмур — гуляют вяло, спрос ниже на "
            f"{round((1 - r.mood_factor) * 100)}%."
        )
    if r.season_demand >= 1.4:
        lines.append(
            f"{r.season_label} — гуляет весь город, спрос "
            f"×{r.season_demand:g}! Лови момент."
        )
    elif r.season_demand >= 1.02:
        lines.append(
            f"{r.season_label}: спрос выше на {round((r.season_demand - 1) * 100)}%."
        )
    elif r.season_demand <= 0.98:
        lines.append(
            f"{r.season_label}: народ по домам, спрос ниже на "
            f"{round((1 - r.season_demand) * 100)}%."
        )
    if r.rep_gain:
        lines.append(f"⭐ +{r.rep_gain} к репутации за бойкую торговлю.")
    if r.premium_unsold:
        lines.append("⚠️ Состоятельных гостей мало — дорогое не разбирают. Репутация решает.")
    return "\n".join(lines)


def income_empty() -> str:
    return "💤 Касса пуста, как башка завсегдатая. Заглядывай позже."


def upgrade_offer(tavern: Tavern, cost: dict) -> str:
    new_stats = balance.stats_for_level(tavern.level + 1)
    return (
        f"🔨 <b>Перестройка до уровня {tavern.level + 1}</b>\n\n"
        f"<b>Выложишь</b>\n"
        f"🪙 {cost['gold']} · 🪵 {cost['wood']} · 🌾 {cost['grain']} · 🌿 {cost['hops']}\n\n"
        f"<b>Получишь</b>\n"
        f"👥 Вместимость — {tavern.capacity} → {new_stats['capacity']}\n"
        f"✨ Комфорт — {tavern.comfort} → {new_stats['comfort']}\n"
        f"💰 Доход — {tavern.income_rate} → {new_stats['income_rate']} 🪙/час\n\n"
        "<i>Плотники деньги вперёд берут и сдачу не дают.</i>"
    )


def upgrade_success(new_level: int) -> str:
    return (
        f"🔨 <b>Готово! Уровень {new_level}.</b>\n"
        f"Соседи завидуют, конкуренты скрипят зубами. "
        f"+{balance.reputation_for_upgrade(new_level)} ⭐ к репутации."
    )


def upgrade_not_enough(cost: dict, player: Player) -> str:
    return (
        "😕 С такими запасами только сортир во дворе пристроить.\n\n"
        f"Надо: 🪙 {cost['gold']} · 🪵 {cost['wood']} · "
        f"🌾 {cost['grain']} · 🌿 {cost['hops']}\n"
        f"У тебя: 🪙 {player.gold} · 🪵 {inventory.get(player, 'wood')} · "
        f"🌾 {inventory.get(player, 'grain')} · 🌿 {inventory.get(player, 'hops')}\n\n"
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

    lines = [
        f"🧍 <b>{escape(player.first_name)}, хозяин кабака</b>",
        "",
        f"<blockquote>Морда кирпичом, руки в мозолях. "
        f"Надето {worn}/{len(it.SLOTS)}.</blockquote>",
    ]
    if craft_line:
        lines += ["", craft_line]
    lines += [
        "",
        "<b>⚔ Боевые</b>",
        f"⚔ Урон — {stats['damage']}",
        f"💥 Крит — {stats['crit']}%",
        f"🛡 Броня — {stats['armor']}",
        f"🍀 Удача — {stats['luck']} "
        f"(счастливая вылазка {balance.lucky_chance(stats['luck'])}%)",
    ]
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
        lines += ["", "<b>💼 Хозяйство</b>", " · ".join(bonuses)]
    lines += ["", "<i>Голый трактирщик — смешной трактирщик. Загляни в кузницу.</i>"]
    return "\n".join(lines)


def forge_screen(player) -> str:
    return (
        "⚒ <b>Кузница Недоливска</b>\n\n"
        "<blockquote>Мастер плюёт на ладони и смотрит на твоё золото. "
        "Один заказ за раз, деньги вперёд, претензии — никогда.</blockquote>\n\n"
        f"🪙 {player.gold} · 🪵 {inventory.get(player, 'wood')} · "
        f"🌾 {inventory.get(player, 'grain')} · 🌿 {inventory.get(player, 'hops')}"
    )


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
    have_mark = lambda k, have: "✅" if have >= c.get(k, 0) else "❌"
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
        f"Цена: 🪙 {c.get('gold',0)} {have_mark('gold', player.gold)} · "
        f"🪵 {c.get('wood',0)} {have_mark('wood', inventory.get(player, 'wood'))} · "
        f"🌾 {c.get('grain',0)} {have_mark('grain', inventory.get(player, 'grain'))} · "
        f"🌿 {c.get('hops',0)} {have_mark('hops', inventory.get(player, 'hops'))}"
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
        f"🔔 Мастер закончил <b>{item.name} {it.TIER_STARS[tier]}</b>!\n"
        "Забирай, пока не перепродал кому побогаче."
    )


def craft_claimed(item, tier: int = 1) -> str:
    from bot.game import items as it

    return (
        f"⚒ <b>{item.name} {it.TIER_STARS[tier]}</b> — твоё!\n"
        f"Надето. {_tier_bonus_line(item, tier)}.\n"
        "Носи и не потеряй по пьяни."
    )
