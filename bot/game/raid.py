"""Глобальный рейд-босс: кооп на весь мир, две фазы.

ФАЗА 1 «Сбор» (GATHER_MINUTES): анонс во все чаты, игроки жмут «Присоединиться»,
текст с обратным отсчётом обновляется. ФАЗА 2 «Битва» (FIGHT_HOURS): босс «дошёл»,
HP подбирается под суммарную СИЛУ записавшихся, бьют ТОЛЬКО записавшиеся. Повержен —
золото из пула делится ПОРОВНУ на всех, кто реально бил; одному случайному из
них с РАВНЫМ шансом падает редкий дроп, редчайшее — снаряга.

Здесь — чистые помощники. DB/IO/рассылка — снаружи (handlers, notifier).
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.game import balance, combat, recipes

GATHER_MINUTES = 20      # сбор перед битвой
FIGHT_HOURS = 1          # окно на добивание

# ── Модель боя (best practice, как у WoW/FFXIV/idle-боссов) ──────────────────
# ТРИГГЕРЫ заклинаний — по ПОРОГАМ HP (BOSSES.script): пропорционально прогрессу,
# читаемо, видно по HP-бару. ДЛИТЕЛЬНОСТЬ эффектов — реальное время (секунды).
# Единственный легитимный ТАЙМЕР — реген при простое (анти-АФК), и дедлайн боя
# (окно FIGHT_HOURS = энрейдж: не успели — ушёл).

# Реген простоя (анти-АФК: никто не бьёт STALL_REGEN_MINUTES → лечится; это про
# реальное бездействие, а не про HP, поэтому намеренно по времени).
STALL_REGEN_MINUTES = 5
STALL_REGEN_PCT = 0.02
SECOND_WIND_AT = 0.30        # S8: порог HP «второго дыхания» (хил + рык, один раз)
SECOND_WIND_HEAL_PCT = 0.20

# Фазы боя по доле HP (тон + сила регена в ярости).
PHASE2_AT = 0.66             # ниже — фаза 2 (разъярён)
PHASE3_AT = 0.33            # ниже — фаза 3 (бешенство)
ENRAGE_REGEN_MULT = {1: 1.0, 2: 1.4, 3: 1.8}

# Эффекты заклинаний (длительность реальная; триггер — по HP, см. BOSSES.script).
ROAR_STUN_SECONDS = 45       # 🗣 рык: оглушает всех бьющих на столько
WARD_DURATION_SEC = 45       # 🛡 щит: урон под ним × WARD_MITIGATE
WARD_MITIGATE = 0.30
CURSE_DURATION_SEC = 45      # 💀 проклятье: удары всех × CURSE_FACTOR
CURSE_FACTOR = 0.55
SUMMON_HP_PCT = 0.10         # 👹 призыв: щит миньонов = доля max_hp
SUMMON_TTL_SEC = 120         # не счистили за столько → вливаются (хил боссу)
SUMMON_MERGE_FRAC = 0.5      # вольются — лечат лишь на половину остатка щита
# 🔒 «В острог!» (Тюремщик): сажает ЛИЧНО топ-урона, не всех (вместо тупого стана).
PIT_SECONDS = 40             # на столько запертый не может бить
PIT_TARGETS = 3              # скольких верхних по урону хватает за раз (апекс — троих)
# 📖 «Стаж» (Тюремщик): чем дольше бой, тем толще шкура — митигация растёт со временем.
TENURE_RAMP_SEC = 600        # за столько выходит на потолок (см. Boss.tenure_max)

# Порог участия для доли золота и трофея: отсекает фри-райдеров (тапнул раз —
# мимо). «Боец» = внёс ≥ MIN_SHARE_HP_PCT от max_hp ЛИБО сделал ≥ MIN_SHARE_HITS.
MIN_SHARE_HP_PCT = 0.01
MIN_SHARE_HITS = 5


@dataclass(frozen=True)
class Boss:
    key: str
    emoji: str
    name: str
    hp_per_power: float     # HP на 1 ед. суммарной силы записавшихся (масштаб по силе)
    min_hp: int             # пол HP (анти-тривиал для слабой/малой пачки)
    gold_pool: int          # делится поровну между всеми, кто бил (краник)
    blurb: str
    # Лут: один бонус-дроп победителю. Веса в промилле (сумма 1000) —
    # чтобы точно держать малые шансы на снарягу. Вид: res:<r>/ingot/gold/gear.
    loot: tuple             # ((вид, вес‰, payload), ...)
    gear_pool: tuple        # из каких предметов может выпасть снаряга с этого босса
    gear_tier_weights: tuple = (80, 18, 2)   # веса ярусов ★/★★/★★★ выпавшей снаряги
    cooldown_min: int = 6   # пауза между ударами одного игрока
    armor: int = 0          # «толща» босса: гасит часть урона за удар (max(1, dmg-armor))
    video: str = ""         # имя ролика в assets/<video>.mp4 (анонс-видео); "" = текст
    sprite: str = ""        # ключ спрайт-босса в мини-аппе (public/boss/<sprite>.png);
                            # "" = фолбэк на крупный эмодзи. Размер кадра и раскладку
                            # анимаций держит реестр SPRITES в components/BossSprite.tsx.
    # Скрипт заклинаний по ПОРОГАМ HP: ((hp%, "ward"/"curse"/"summon"/"roar"/"pit"), …),
    # по убыванию %. Каждый каст срабатывает один раз, когда HP падает до порога —
    # как сигнатурные способности рейд-боссов. Низкие пороги гуще = «ярость» к концу.
    script: tuple = ()
    pit: bool = False       # 🔒 умеет сажать в острог (личный лок топ-урона + так же
                            #    «второе дыхание» вместо общего стана). См. spell "pit".
    tenure_max: float = 0.0  # 📖 «стаж»: макс. доля срезаемого урона к концу боя (0=нет)
    # Персональная СИЛА баффов (0 = дефолт-константы). Меньше ward_mult/curse_factor =
    # ЖЁСТЧЕ (урон режется сильнее); больше summon_pct = толще выводок-щит.
    ward_mult: float = 0.0     # 🛡 доля проходящего урона под щитом (деф. WARD_MITIGATE)
    curse_factor: float = 0.0  # 💀 множитель урона под проклятьем (деф. CURSE_FACTOR)
    summon_pct: float = 0.0    # 👹 щит выводка = доля max_hp (деф. SUMMON_HP_PCT)
    # Реплики-субтитры босса (RaidSheet печатает их в бою). Кортеж пар
    # (событие, фраза): intro (вход) / ward / curse / summon / roar / death.
    # Пусто → босс молчит (как было). Событие ключуется тем же спелл-именем.
    barks: tuple = ()
    # Лор-реплики на экране СБОРА (речевое облако у рта, циклом за 20 мин ожидания):
    # предыстория босса — кто он, откуда, отчего озлобился. Пусто → облака нет.
    lore: tuple = ()


# Ярусы редкости бонус-дропа (для подписи в сообщениях).
RARITY = {"common": "обычный", "rare": "🔶 РЕДКИЙ", "legendary": "💎 ЛЕГЕНДАРНЫЙ"}


def _rarity_of(kind: str) -> str:
    """Снаряга — легендарное (редчайшее), золото-джекпот — редкое, прочее — обычное."""
    if kind == "gear":
        return "legendary"
    if kind == "gold":
        return "rare"
    return "common"


# Уровни: от слабого к грозному. Шанс и качество снаряги растут с тиром босса.
# Снаряга — редчайшее: 1.5% / 3.5% / 7% за убийство. Топ-вещи ★★★ — только с Дракона.
BOSSES: dict[str, Boss] = {
    "rat_king": Boss(
        "rat_king", "🐀", "Крысиный Король", 80, 3000, 520,
        "Размером с борова, наглый как сборщик податей. Вылез из-под пола и жрёт "
        "всё, до чего дотянется. Прихлопнуть можно — но всем миром, по одному только "
        "лапу отгрызёт.",
        (("res:grain", 455, ("grain", 20, 40)), ("res:hops", 320, ("hops", 15, 30)),
         ("gold", 145, (60, 120)), ("gear", 80, None)),   # 8% — лёгкий босс, щедр на (слабую) снарягу
        gear_pool=("rat_crown", "rat_pelt", "rat_tail"),
        gear_tier_weights=(82, 16, 2), cooldown_min=0, armor=3, video="rat_king",
        script=((80, "curse"), (62, "summon"), (45, "roar"),
                (30, "curse"), (16, "summon"))),    # крысиный рой + чумная зараза
    "bog_troll": Boss(
        "bog_troll", "👹", "Болотный Тролль", 65, 2000, 1560,
        "Гора смрадного мяса по пояс в тине. Каждый шаг — как телега с навозом, "
        "каждый замах — как падающий дуб. Сунешься один — раскатает в блин.",
        (("res:ore", 465, ("ore", 25, 50)), ("ingot", 300, (10, 20)),
         ("gold", 185, (150, 300)), ("gear", 50, None)),   # 5% — середняк
        gear_pool=("troll_club", "troll_hide", "troll_eye"),
        gear_tier_weights=(50, 42, 8), cooldown_min=0, armor=8, video="bog_troll",
        script=((85, "ward"), (66, "summon"), (50, "roar"),
                (38, "ward"), (25, "summon"), (12, "roar"))),  # шкура-щит + выводок
    "demon_slime": Boss(
        "demon_slime", "😈", "Адский Слизень", 72, 2400, 2400,
        "Выперло из преисподней прямо посреди торга — туша смолы с рогами, харкает "
        "огнём и плодит из себя мелких бесов. Ползёт на кабаки, оставляя выжженный "
        "след. В одиночку не сунешься — слижет вместе с вывеской.",
        (("res:ore", 430, ("ore", 30, 55)), ("ingot", 320, (15, 28)),
         ("gold", 210, (220, 420)), ("gear", 40, None)),   # 4% — сильный босс
        gear_pool=("demon_fang", "demon_hide", "demon_core"),
        gear_tier_weights=(34, 50, 16), cooldown_min=0, armor=11, sprite="demon_slime",
        script=((88, "curse"), (74, "summon"), (60, "roar"), (48, "ward"),
                (36, "summon"), (24, "curse"), (12, "roar"))),   # бесы + адское пламя
    "jailer": Boss(
        "jailer", "🔨", "Батог Мясомял", 85, 3200, 4400,
        "Тридцать лет он держал лучшую корчму на тракте — пока не схоронил жену да "
        "малую дочь, а с ними и всё людское. Ныне Батог Мясомял, городской кат, знает "
        "один закон: кто пил да гулял — тот виновен. Из ямы под ратушей он встаёт с "
        "дубиной, что валит быка, и связкой кандалов на буянов; земля гудит под его "
        "поступью, стража сползается на рёв. В одиночку не суйся — закуёт, засадит и "
        "запорет до костей. Только всем Недоливском свалим ката.",
        (("res:wood", 395, ("wood", 45, 80)), ("ingot", 340, (24, 44)),
         ("gold", 205, (360, 660)), ("gear", 60, None)),   # 6% — АПЕКС, сильнее дракона, топ-лут
        gear_pool=("jailer_club", "jailer_coat", "jailer_shackles"),
        gear_tier_weights=(10, 44, 46), cooldown_min=0, armor=16, sprite="jailer",
        pit=True, tenure_max=0.30,          # 🔒 острог топ-3 + 📖 «стаж» до −30% (уникально; дракон 0)
        ward_mult=0.27, curse_factor=0.52, summon_pct=0.13,   # его щит/проклятье/выводок злее дефолта,
        #   но НЕ множатся в непробиваемость (аудит: 0.22×0.45×стаж = ~1 урон в окне)
        script=((90, "ward"), (80, "curse"), (70, "pit"), (60, "summon"), (50, "ward"),
                (40, "curse"), (30, "pit"), (20, "summon"), (12, "curse"), (6, "pit")),  # плотно, к концу — гуще
        barks=(("intro", "Догулялись, пьянь. Батог пришёл — всех перепишу да в яму."),
               ("ward", "Дубьём меня? А ну к стенке, пёс!"),
               ("curse", "Держи кандалы, гуляка!"),
               ("summon", "Стража-а! Волоки всю ораву сюда!"),
               ("pit", "Тебя, буян, — в острог! Волоки за решётку, к остальным!"),
               ("death", "Кто ж… теперь… стеречь будет… голытьбу…")),
        lore=(  # — трагедия —
              "Думаете, Батог с колыбели такой? Тридцать годков держал я корчму «Тёплый Очаг» — лучшую на тракте.",
              "Марьюшка, жёнушка, разливала гостям — от одной её улыбки и хмель слаще казался.",
              "А доченька, Алёнка, семи годков, меж столов порхала: каждому — кружку да ласковое словцо.",
              "Вечерами клала головку мне на плечо: „Тятя, спой“. И голосок её — что колокольчик по первому снегу.",
              "В ту осень заехали гуляки — сытые, злые, хмельные. Крушили всё. Я сказал: будет, по домам.",
              "Они лишь смеялись. А в ночь подпёрли двери снаружи колом… и пустили по крыше красного петуха.",
              "Проснулся в дыму. Рвусь в горницу — балка рухнула поперёк. Слышу: „Тя-тя-а!“ — Алёнка зовёт…",
              "…и звала, пока не смолкла. Я не добрался. Не добрался, слышите вы?",
              "Наутро выгреб из золы два колечка — своё да её, совсем крохотное. Всё, что осталось от «Очага».",
              "Так и стал катом. Двадцать годков в остроге отстоял — насмотрелся на вас, гуляк, на десять жизней.",
              "Батог мой не простой: что зарубка — то чья-то пьяная ночка. Живого места на нём уже нет.",
              # — мостик к байкам —
              "Э, да что душу травить. Раз уж ждём народ — потешу вас, каких дурней сюда волокли.",
              # — байки про Недоливск (бытовые) —
              "Мужик по пьяни в чужую избу забрёл, лёг да уснул. Хозяйка утром: „Ты чей будешь?“ — „Твой, Люба, твой!“ А её Клавдией звать.",
              "Другой сам в камеру просился — от жены хоронился. „У вас, — грит, — хоть сковородой не достанет.“ Неделю жил, за уши не выволочь.",
              "Третий у соседа забор свёл — свой чинить. У того самого соседа, с кем за этот забор третий год и грызётся.",
              "Бабка самогон гнала — до того забористый, что петух с одного глотка по-людски заговорил. Забрал обоих: и бабку, и петуха-свидетеля.",
              "Один нарочно окно в управе высадил — чтоб посадили. „Три годика, — молит, — дай, от тёщи отдохну!“",
              "Штраф мне гусём принёс. Гусь вырвался, мэра за ляжку — цап! Мэр гуся и помиловал: „Хоть кто-то, — грит, — в городе при деле.“",
              "Бабу — мужа хватилась, пропал! Через три дня в соседской бане отрыли. „Я, — грит, — в отъезде был, по делам.“ Три дня в бане.",
              "Сборщику податей палец откусил — „за колбасу, — грит, — принял“. Тот теперь подати в перчатках считает.",
              "А отчего Недоливск-то? Шинкарь на палец недолил — ему кружкой в лоб. С того и повелось: что ни день — недолив да мордобой.",
              # — обратно к угрозе (кольцует) —
              "Ну да посмеялись — и будет. Батог не за смехом пришёл. За Алёнку пришёл. Готовьтесь, голубчики.")),
    "dragon": Boss(
        "dragon", "🐲", "Древний Змей", 80, 3000, 3900,
        "Древний, злой и голодный до золота. Накроет тенью пол-Недоливска, дохнёт "
        "огнём — и от кабака одни головешки. Идёт весь мир разом, иначе всем крышка.",
        (("ingot", 520, (25, 45)), ("res:honey", 300, ("honey", 30, 60)),
         ("gold", 150, (300, 600)), ("gear", 30, None)),   # 3% — сильный босс, снаряга редкая (престиж, она же 2× мощнее)
        gear_pool=("dragon_fang", "dragon_scale", "dragon_heart"),
        gear_tier_weights=(14, 50, 36), cooldown_min=0, armor=15, video="dragon",
        script=((90, "ward"), (78, "curse"), (66, "summon"), (55, "roar"),
                (45, "ward"), (38, "curse"), (30, "summon"), (22, "roar"),
                (14, "ward"), (8, "curse"))),   # всё, и гуще к концу (бешенство)
}


def gear_drop_pct(boss_key: str) -> float:
    """Шанс (%), что бонус-дроп победителю окажется ЭКСКЛЮЗИВНОЙ снарягой.
    Считается из весов лута (промилле, сумма 1000) — для анонса/прозрачности."""
    spec = BOSSES.get(boss_key)
    if spec is None:
        return 0.0
    total = sum(w for _, w, _ in spec.loot)
    gear = sum(w for tag, w, _ in spec.loot if tag == "gear")
    return round(100 * gear / total, 1) if total else 0.0


# Лёгкий кэш «есть ли живой рейд» — чтобы меню таверны рисовало кнопку без
# запроса к БД на каждый рендер. Ставит спавн (сразу) и нотифаер (раз в тик).
_active_raid_id: int | None = None


def set_active(raid_id: int | None) -> None:
    global _active_raid_id
    _active_raid_id = raid_id


def active_id() -> int | None:
    return _active_raid_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def gather_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(minutes=GATHER_MINUTES)


def fight_until(now: datetime | None = None) -> datetime:
    return (now or _now()) + timedelta(hours=FIGHT_HOURS)


DEFAULT_POWER = 30   # «сила» по умолчанию (старые записи без pow / фолбэк)

# HP растёт от суммарной силы СУБЛИНЕЙНО (затухание): сильнее/больше пачка валит
# ЗАМЕТНО быстрее — прокачка и снаряга реально дают результат, — но не мгновенно.
# Якорь HP_REF_POWER: на этой силе HP = hp_per_power×ref (как было бы линейно),
# вокруг неё кривая гнётся показателем HP_POWER_EXP (<1 → время падает с силой).
HP_REF_POWER = 80
HP_POWER_EXP = 0.75


def hp_for_power(boss_key: str, power: int) -> int:
    """HP босса от суммарной СИЛЫ записавшихся (урон/удар), сублинейно (затухание):
    HP = hp_per_power × ref^(1−exp) × сила^exp. Сильнее пачка → выше HP, но время
    убийства (HP/урон) падает ~как сила^(exp−1). Пол (min_hp) — анти-тривиал."""
    spec = BOSSES[boss_key]
    scaled = (spec.hp_per_power * HP_REF_POWER ** (1 - HP_POWER_EXP)
              * max(1, power) ** HP_POWER_EXP)
    return max(spec.min_hp, round(scaled))


def roster_power(boss) -> int:
    """Сумма сил записавшихся (из contributions[pid]['pow']; фолбэк DEFAULT_POWER)."""
    recs = (boss.contributions or {}).values()
    total = sum(int(r.get("pow", DEFAULT_POWER) or DEFAULT_POWER) for r in recs)
    return total or DEFAULT_POWER


def boss_start_hp(boss) -> int:
    """HP босса на старте битвы — от суммарной силы записавшихся."""
    return hp_for_power(boss.boss_key, roster_power(boss))


def registered_count(boss) -> int:
    return len(boss.contributions or {})


def is_registered(boss, player_id: int) -> bool:
    return str(player_id) in (boss.contributions or {})


def register(boss, player) -> bool:
    """Записать игрока в рейд (фаза сбора). False — уже записан."""
    c = dict(boss.contributions or {})
    pid = str(player.id)
    if pid in c:
        return False
    c[pid] = {"dmg": 0, "hits": 0, "name": player.first_name or pid,
              "pow": player_power(player)}     # сила → масштаб HP босса
    boss.contributions = c
    return True


def hp_bar(hp: int, max_hp: int, width: int = 12) -> str:
    hp = max(0, hp)
    filled = round(width * hp / max_hp) if max_hp else 0
    return "🟥" * filled + "⬛" * (width - filled)


def player_power(player) -> int:
    """Ожидаемый сырой урон игрока по боссу за удар (база×(1+крит)) — мера «силы»
    для масштаба HP босса. Тот же расчёт, что и средний player_damage без разброса."""
    stats = combat.player_stats(player)
    base = (balance.BASE_DAMAGE + stats.get("damage", 0)
            + (getattr(player, "level", 1) or 1) * balance.LEVEL_DAMAGE)
    crit = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0)) / 100
    return max(1, round(base * (1 + crit)))


# В рейде у игрока нет HP/уворота (это DPS-гонка по боссу, он не бьёт в ответ),
# поэтому «сытость» (hp-фляга) и «ловкость» (уворот-фляга) НЕ пропадали бы зря —
# конвертируем их в доп. урон за удар: сытый/ловкий боец бьёт крепче и чище.
# Так эксклюзив-«Пир зодчих» (+45❤) и обычные жаркое/пирог/мёд перестают быть
# мёртвым грузом в рейде. dmg/crit/antidote применяются как есть.
RAID_HP_TO_DMG = 3      # 1 урон за каждые 3 ❤ фляги (feast 45 → +15 урона)
RAID_DODGE_TO_DMG = 4   # 1 урон за каждые 4% уворота фляги (loaf 28 → +7 урона)


def _effect_of(key: str) -> dict:
    """Единый резолвер эффектов фляги: сперва статическое благо (FLASK_EFFECTS), затем
    тайный ИИ-рецепт (recipes-кэш). Одна котировка — метка на экране == эффект в бою."""
    return balance.FLASK_EFFECTS.get(key) or recipes.effects_for_key(key) or {}


def flask_mods(keys: list[str] | None) -> dict:
    """Суммарный боевой эффект выпитого на рейд: урон (вкл. конверсию hp/уворота)/
    крит/противоядие. См. RAID_HP_TO_DMG — почему сытость/ловкость идут в урон."""
    out = {"dmg": 0, "crit": 0, "antidote": False}
    for k in keys or []:
        eff = _effect_of(k)
        out["dmg"] += (eff.get("dmg", 0)
                       + eff.get("hp", 0) // RAID_HP_TO_DMG
                       + eff.get("dodge", 0) // RAID_DODGE_TO_DMG)
        out["crit"] += eff.get("crit", 0)
        out["antidote"] = out["antidote"] or bool(eff.get("antidote"))
    return out


def flask_label(key: str) -> str:
    """Что фляга даёт ИМЕННО В РЕЙДЕ (показ=действие: та же flask_mods, что и в бою).
    Метка из FLASK_EFFECTS («+45❤») в рейде врала бы — hp/уворот тут идут в урон."""
    m = flask_mods([key])
    parts = []
    if m["dmg"]:
        parts.append(f"+{m['dmg']} урона")
    if m["crit"]:
        parts.append(f"+{m['crit']}% крита")
    if m["antidote"]:
        parts.append("снимает проклятье")
    return ", ".join(parts) or "—"


def player_damage(player, rng: random.Random | None = None,
                  flask: dict | None = None) -> tuple[int, bool]:
    """Урон игрока по боссу за удар: снаряга + уровень + фляга, крит ×2, разброс ±20%."""
    rng = rng or random
    fl = flask or {}
    stats = combat.player_stats(player)
    base = (balance.BASE_DAMAGE + stats.get("damage", 0)
            + (player.level or 1) * balance.LEVEL_DAMAGE + fl.get("dmg", 0))
    crit_pct = min(balance.HUNT_CRIT_CAP, stats.get("crit", 0) + fl.get("crit", 0))
    crit = rng.randint(1, 100) <= crit_pct
    dmg = base * (2 if crit else 1) * rng.uniform(0.8, 1.2)
    return max(1, int(dmg)), crit


def _iso_left(iso: str | None, now: datetime) -> int:
    """Секунд до момента iso (0 если прошёл/нет)."""
    if not iso:
        return 0
    try:
        return max(0, int(datetime.fromisoformat(iso).timestamp() - now.timestamp()))
    except (ValueError, TypeError):
        return 0


def stun_left(boss, now: datetime | None = None) -> int:
    """Секунд оглушения босса (рык D2 / второе дыхание S8) — общий на всех."""
    return _iso_left((boss.state or {}).get("stun_until"), now or _now())


def pit_left(boss, player_id: int, now: datetime | None = None) -> int:
    """🔒 Секунд, что игрок сидит в остроге (ЛИЧНЫЙ лок топ-урона, не общий стан)."""
    pit = (boss.state or {}).get("pit") or {}
    return _iso_left(pit.get(str(player_id)), now or _now())


def pit_who(boss, now: datetime | None = None) -> list[str]:
    """Имена бойцов, что сейчас в остроге (для баннера/подписи)."""
    now = now or _now()
    pit = (boss.state or {}).get("pit") or {}
    contrib = boss.contributions or {}
    return [(contrib.get(pid) or {}).get("name") or "боец"
            for pid in pit if _iso_left(pit[pid], now) > 0]


def cooldown_left(boss, player_id: int, now: datetime | None = None) -> int:
    """Секунд до следующего удара: max(личный кд, общий стан, острог этого игрока)."""
    now = now or _now()
    rec = (boss.contributions or {}).get(str(player_id))
    personal = 0
    if rec and isinstance(rec.get("last"), str):
        cd = BOSSES[boss.boss_key].cooldown_min * 60
        last_dt = datetime.fromisoformat(rec["last"]) + timedelta(seconds=cd)
        personal = _iso_left(last_dt.isoformat(), now)
    return max(personal, stun_left(boss, now), pit_left(boss, player_id, now))


def stunned(boss, player_id: int, now: datetime | None = None) -> bool:
    """Оглушение — главная причина ждать (рык/второе дыхание сильнее личного кд)."""
    now = now or _now()
    return stun_left(boss, now) >= cooldown_left(boss, player_id, now) > 0


def in_pit(boss, player_id: int, now: datetime | None = None) -> bool:
    """🔒 Заперт ли игрок в остроге (сильнее личного кд — главная причина ждать)."""
    now = now or _now()
    return pit_left(boss, player_id, now) >= cooldown_left(boss, player_id, now) > 0


def _fight_start(boss) -> datetime:
    if boss.ends_at is not None:
        e = boss.ends_at
        if e.tzinfo is None:
            e = e.replace(tzinfo=timezone.utc)
        return e - timedelta(hours=FIGHT_HOURS)
    return _now()


def last_hit_at(boss) -> datetime:
    """Когда по боссу били в последний раз (для E2). Нет ударов — старт боя."""
    times = [datetime.fromisoformat(r["last"]) for r in (boss.contributions or {}).values()
             if isinstance(r.get("last"), str)]
    return max(times) if times else _fight_start(boss)


def phase(boss) -> int:
    """Фаза боя по доле HP: 1 (>66%), 2 (33–66%, разъярён), 3 (<33%, бешенство).
    Чем ниже — тем сильнее реген и тем чаще касты (см. ENRAGE_*)."""
    if not boss.max_hp or boss.max_hp <= 0:
        return 1
    frac = max(0, boss.hp) / boss.max_hp
    if frac > PHASE2_AT:
        return 1
    if frac > PHASE3_AT:
        return 2
    return 3


def regen_if_stalled(boss, now: datetime | None = None) -> int:
    """E2: если по боссу не били STALL_REGEN_MINUTES — лечит часть HP. С фазой
    ярости лечит сильнее (ENRAGE_REGEN_MULT). Вернёт сколько подлечил."""
    now = now or _now()
    if boss.max_hp <= 0 or boss.hp >= boss.max_hp:
        return 0
    if (now - last_hit_at(boss)).total_seconds() < STALL_REGEN_MINUTES * 60:
        return 0
    mult = ENRAGE_REGEN_MULT.get(phase(boss), 1.0)
    heal = max(1, int(boss.max_hp * STALL_REGEN_PCT * mult))
    boss.hp = min(boss.max_hp, boss.hp + heal)
    return heal


def maybe_second_wind(boss, now: datetime | None = None) -> bool:
    """S8: один раз на ≤30% HP — хил + рык (оглушение всех). True — сработало."""
    now = now or _now()
    st = boss.state or {}
    if st.get("second_wind") or boss.max_hp <= 0:
        return False
    if not (0 < boss.hp <= boss.max_hp * SECOND_WIND_AT):
        return False
    boss.hp = min(boss.max_hp, boss.hp + int(boss.max_hp * SECOND_WIND_HEAL_PCT))
    st = dict(boss.state or {})
    st["second_wind"] = True
    spec = BOSSES.get(boss.boss_key)
    if spec and spec.pit:                # 🔒 «острог»-босс сажает топ-урона (не общий стан)
        _imprison(st, boss, now)
    else:
        st["stun_until"] = (now + timedelta(seconds=ROAR_STUN_SECONDS)).isoformat()
    boss.state = st
    return True


# ── Спеллбук: щит / проклятье / призыв миньонов ─────────────────────────────

def ward_left(boss, now: datetime | None = None) -> int:
    """Секунд активного щита (🛡): пока тикает — входящий урон режется."""
    return _iso_left((boss.state or {}).get("ward_until"), now or _now())


def curse_left(boss, now: datetime | None = None) -> int:
    """Секунд активного проклятья (💀): пока тикает — удары всех ослаблены."""
    return _iso_left((boss.state or {}).get("curse_until"), now or _now())


def adds_hp(boss) -> int:
    """HP-щит призванных миньонов (👹): бьётся первым, пока > 0."""
    return int((boss.state or {}).get("adds_hp", 0) or 0)


def _imprison(st: dict, boss, now: datetime) -> list[int]:
    """🔒 Посадить в острог топ по урону (личный лок, не общий стан). Мутирует st['pit']
    (pid→до-когда). ВСЕГДА оставляет ≥1 бойца на свободе — иначе соло/малую пачку
    залочит целиком, а босс на простое регенит → вечный бой. Возвращает id посаженных."""
    contrib = boss.contributions or {}
    top = sorted((kv for kv in contrib.items() if int((kv[1] or {}).get("dmg", 0)) > 0),
                 key=lambda kv: -int((kv[1] or {}).get("dmg", 0)))
    n = min(PIT_TARGETS, max(0, len(top) - 1))          # хотя бы одного не сажаем
    targets = [int(pid) for pid, _ in top[:n]]
    if targets:
        pit = dict(st.get("pit") or {})
        until = (now + timedelta(seconds=PIT_SECONDS)).isoformat()
        for pid in targets:
            pit[str(pid)] = until
        st["pit"] = pit
    return targets


def _apply_spell(st: dict, key: str, now: datetime, boss) -> bool:
    """Наложить эффект каста на копию state. False — каст «пустой» (например призыв
    при живом выводке): порог всё равно считаем взятым, но события не выдаём."""
    if key == "ward":
        st["ward_until"] = (now + timedelta(seconds=WARD_DURATION_SEC)).isoformat()
        return True
    if key == "curse":
        st["curse_until"] = (now + timedelta(seconds=CURSE_DURATION_SEC)).isoformat()
        return True
    if key == "roar":
        st["stun_until"] = (now + timedelta(seconds=ROAR_STUN_SECONDS)).isoformat()
        return True
    if key == "pit":                                # 🔒 «В острог!» — личный лок топ-урона
        return bool(_imprison(st, boss, now))       # некого сажать (пустой ростер) → пустой каст
    if key == "summon":
        if int(st.get("adds_hp", 0) or 0) > 0:      # выводок ещё жив — не плодим
            return False
        spec = BOSSES.get(boss.boss_key)
        pct = (spec and spec.summon_pct) or SUMMON_HP_PCT
        st["adds_hp"] = max(1, int(boss.max_hp * pct))
        st["adds_until"] = (now + timedelta(seconds=SUMMON_TTL_SEC)).isoformat()
        return True
    return False


def script_cast(boss, now: datetime | None = None) -> list[str]:
    """Сигнатурные заклинания по ПОРОГАМ HP (BOSSES.script): каждый порог — один
    раз, как только HP до него падает (как способности рейд-боссов). Зовётся на
    каждом ударе — спелл бьёт мгновенно на пробитии порога. Возвращает ключи
    сработавших каст (+ «enrage2/3» при входе в фазу ярости)."""
    now = now or _now()
    spec = BOSSES.get(boss.boss_key)
    if spec is None or getattr(boss, "status", "active") != "active" or boss.max_hp <= 0:
        return []
    pct = 100 * max(0, boss.hp) / boss.max_hp
    st = dict(boss.state or {})
    fired = list(st.get("cast_done", []))
    events: list[str] = []
    for i, (thr, key) in enumerate(spec.script):
        if i in fired or pct > thr:
            continue
        if _apply_spell(st, key, now, boss):
            events.append(key)
        fired.append(i)                 # порог взят (даже если каст «пустой»)
    st["cast_done"] = fired
    ph = phase(boss)                    # объявление ярости — один раз на фазу
    if ph >= 2 and int(st.get("phase", 1)) < ph:
        st["phase"] = ph
        events.append("enrage2" if ph == 2 else "enrage3")
    boss.state = st
    return events


def cast_tick(boss, now: datetime | None = None) -> list[str]:
    """Ход босса по ТАЙМЕРУ (нотифаер, раз в минуту): только временны́е штуки —
    реген при простое (анти-АФК) и «вливание» не счищенных вовремя миньонов. Плюс
    добор HP-каст, если порог проскочили между тиками. Мутирует boss; коммит снаружи."""
    now = now or _now()
    spec = BOSSES.get(boss.boss_key)
    if spec is None or boss.status != "active":
        return []
    events: list[str] = []
    st = dict(boss.state or {})
    adds_until = st.get("adds_until")
    if st.get("adds_hp") and adds_until and _iso_left(adds_until, now) == 0:
        boss.hp = min(boss.max_hp, boss.hp + int(st.get("adds_hp", 0) * SUMMON_MERGE_FRAC))
        st["adds_hp"] = 0
        st.pop("adds_until", None)
        boss.state = st
        events.append("adds_merge")
    if regen_if_stalled(boss, now) > 0:
        events.append("regen")
    events += script_cast(boss, now)    # страховка: добрать пороги, если проскочили
    return events


def mitigate(boss_key: str, raw: int) -> int:
    """Срезать «толщей» босса ПРОЦЕНТНО (как на охоте): урон × K/(K+броня).
    Плоское вычитание топило слабых наглухо в 1 — а так слабый хоть царапает,
    снаряга/уровень усиливают, толстый босс (выше броня) режет процент сильнее.
    Урон всегда ≥1."""
    armor = BOSSES[boss_key].armor
    return max(1, round(raw * balance.HUNT_ARMOR_K / (balance.HUNT_ARMOR_K + armor)))


def tenure_frac(boss, now: datetime | None = None) -> float:
    """📖 «Стаж»: доля срезаемого урона от длительности боя (0..tenure_max). Чем дольше
    тянут — тем толще шкура ката; награда за быстрый килл. 0 у боссов без стажа."""
    spec = BOSSES.get(boss.boss_key)
    if not spec or spec.tenure_max <= 0:
        return 0.0
    elapsed = ((now or _now()) - _fight_start(boss)).total_seconds()
    return round(spec.tenure_max * min(1.0, max(0.0, elapsed) / TENURE_RAMP_SEC), 3)


def apply_hit(boss, player, dmg: int, now: datetime | None = None,
              credit: int | None = None) -> None:
    """Снять HP боссу на dmg и записать вклад игрока. credit — сколько засчитать
    в лидерборд (по умолчанию = dmg; при бое по миньонам туда идёт и урон по
    щиту, а боссу — только остаток). Мутирует boss; коммит снаружи."""
    now = now or _now()
    c = dict(boss.contributions or {})
    pid = str(player.id)
    # ВАЖНО: rec — СВЕЖАЯ копия (dict(...)), а не общий вложенный объект. Если
    # менять вложенный словарь «на месте», он же сидит в снимке SQLAlchemy для
    # сравнения — снимок «портится», новое значение кажется равным старому, и
    # колонка contributions НЕ пишется (урон теряется, хотя hp снимается). Копия
    # рвёт эту связь: новое значение реально отличается от снимка → запись идёт.
    rec = dict(c.get(pid) or {"dmg": 0, "hits": 0, "name": player.first_name or pid})
    rec["dmg"] = int(rec.get("dmg", 0)) + (dmg if credit is None else credit)
    rec["hits"] = int(rec.get("hits", 0)) + 1
    rec["last"] = now.isoformat()
    c[pid] = rec
    boss.contributions = c
    boss.hp = max(0, boss.hp - dmg)


def resolve_hit(boss, player, now: datetime | None = None,
                rng: random.Random | None = None,
                flask_keys: list[str] | None = None) -> dict:
    """Единый расчёт удара по боссу со всеми механиками и запись результата.
    Порядок: урон игрока → 💀 проклятье (×CURSE) → 🛡 щит (×WARD) → толща-броня
    → 👹 миньоны (сперва их щит, остаток — боссу). Мутирует boss; коммит снаружи.
    Возвращает флаги для тоста: dmg (по боссу), crit, soaked (съедено бронёй),
    curse/ward (активны ли), adds_dmg, adds_left, adds_cleared, casts (сработавшие
    на этом ударе HP-пороговые заклинания — для пуша бойцам)."""
    now = now or _now()
    mods = flask_mods(flask_keys)
    raw, crit = player_damage(player, rng, mods)

    spec = BOSSES.get(boss.boss_key)
    # сбитень отпаивает от проклятья босса — урон не режется
    curse = curse_left(boss, now) > 0 and not mods["antidote"]
    if curse:
        raw = max(1, round(raw * ((spec and spec.curse_factor) or CURSE_FACTOR)))

    ward = ward_left(boss, now) > 0
    after_armor = mitigate(boss.boss_key, raw)        # толща-броня (процентом)
    wmult = (spec and spec.ward_mult) or WARD_MITIGATE
    dmg = max(1, round(after_armor * wmult)) if ward else after_armor
    ten = tenure_frac(boss, now)                      # 📖 стаж: чем дольше бой, тем толще
    if ten > 0:
        dmg = max(1, round(dmg * (1 - ten)))
    soaked = max(0, raw - dmg)

    # Сперва бьём щит миньонов; остаток уходит в HP босса.
    adds = adds_hp(boss)
    adds_dmg = min(adds, dmg) if adds > 0 else 0
    boss_dmg = dmg - adds_dmg
    adds_cleared = False
    if adds_dmg:
        st = dict(boss.state or {})
        st["adds_hp"] = adds - adds_dmg
        if st["adds_hp"] <= 0:
            st["adds_hp"] = 0
            st.pop("adds_until", None)
            adds_cleared = True
        boss.state = st

    apply_hit(boss, player, boss_dmg, now, credit=dmg)
    casts = script_cast(boss, now)   # HP-пороговые заклинания срабатывают на ударе
    return {"dmg": boss_dmg, "crit": crit, "soaked": soaked,
            "curse": curse, "ward": ward, "adds_dmg": adds_dmg,
            "adds_left": adds_hp(boss), "adds_cleared": adds_cleared,
            "casts": casts}


def is_dead(boss) -> bool:
    return boss.status == "active" and boss.hp <= 0


def settle(boss, rng: random.Random | None = None) -> dict:
    """План раздачи: {gold: {pid:int}, winner: pid|None, drop: dict|None}.
    Золото — пул ПОРОВНУ на всех, кто реально бил; редкий дроп — одному
    случайному из них с РАВНЫМ шансом (не по вкладу — чистый кооп)."""
    rng = rng or random
    hitters = {int(p): r for p, r in (boss.contributions or {}).items()
               if r.get("dmg", 0) > 0}                     # вообще нанёс урон
    gate = max(1, round((getattr(boss, "max_hp", 0) or 0) * MIN_SHARE_HP_PCT))
    # «Бойцы» — кто внёс ≥1% HP ИЛИ ≥5 ударов; фолбэк к hitters, если никто не дотянул
    # (чтобы убийство всегда кому-то платило). Доля и трофей — только среди них.
    contrib = {p: r for p, r in hitters.items()
               if r.get("dmg", 0) >= gate or r.get("hits", 0) >= MIN_SHARE_HITS} or hitters
    spec = BOSSES[boss.boss_key]
    n = len(contrib)
    # Строго ≤ пула: доля = пол(пул/бойцов). При толпе больше пула доля=0
    # (золото не «печатается» сверх пула — целостность глобальной экономики).
    per = spec.gold_pool // n if n else 0
    gold = {pid: per for pid in contrib} if per else {}
    winner, drop = None, None
    forced = getattr(boss, "forced", None) or None
    if contrib and forced:                                 # админ-рига: фикс. трофей игроку
        winner = (int(forced["winner"]) if forced.get("winner") is not None
                  else rng.choice(list(contrib)))
        if forced.get("drop"):
            drop = dict(forced["drop"])
            drop.setdefault("rarity", _rarity_of(drop.get("kind", "")))
        return {"gold": gold, "winner": winner, "drop": drop}
    if contrib:
        pids = list(contrib)
        winner = rng.choice(pids)                          # равный шанс каждому
        tag, _w, payload = rng.choices(spec.loot, weights=[w for _, w, _ in spec.loot])[0]
        if tag == "gear":
            tier = rng.choices((1, 2, 3), weights=spec.gear_tier_weights)[0]
            drop = {"kind": "gear", "item_id": rng.choice(spec.gear_pool), "tier": tier}
        elif tag == "ingot":
            drop = {"kind": "res", "res": "ingot", "qty": rng.randint(*payload)}
        elif tag == "gold":
            drop = {"kind": "gold", "qty": rng.randint(*payload)}
        else:  # res:<name>
            res, lo, hi = payload
            drop = {"kind": "res", "res": res, "qty": rng.randint(lo, hi)}
        drop["rarity"] = _rarity_of(tag)
    return {"gold": gold, "winner": winner, "drop": drop}
