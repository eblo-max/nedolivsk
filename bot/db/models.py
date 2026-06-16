from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


class Player(Base):
    """Игрок = пользователь Telegram."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    level: Mapped[int] = mapped_column(default=1)
    gold: Mapped[int] = mapped_column(default=100)
    reputation: Mapped[int] = mapped_column(default=0)
    region: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    # «Домашний» общий чат игрока (где он играл через «гг») — туда шлём
    # уведомления о готовности; None -> в личку.
    chat_id: Mapped[int | None] = mapped_column(BigInteger)

    # Инвентарь сырья (Ярус 0): {id: количество}
    inventory: Mapped[dict] = mapped_column(JSONB, default=dict)

    # DEPRECATED: данные перелиты в inventory (миграция в base.py).
    # Колонки оставлены ради старых БД; в коде больше не используются.
    wood: Mapped[int] = mapped_column(default=10)
    grain: Mapped[int] = mapped_column(default=10)
    hops: Mapped[int] = mapped_column(default=5)

    # Бригады на вылазках (мультислот): [{resource, ends_at, notified}]
    expeditions: Mapped[list] = mapped_column(JSONB, default=list)

    # DEPRECATED: одиночная вылазка — перелита в expeditions (миграция в base.py)
    expedition_resource: Mapped[str | None] = mapped_column(String(16))
    expedition_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    expedition_notified: Mapped[bool] = mapped_column(default=False)

    # Экипировка и крафт
    equipment: Mapped[dict] = mapped_column(JSONB, default=dict)
    craft_item: Mapped[str | None] = mapped_column(String(32))
    craft_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    craft_notified: Mapped[bool] = mapped_column(default=False)

    # Охота: постоянное здоровье (макс = BASE_HP), регенится со временем от hp_at.
    hunt_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hp: Mapped[int | None] = mapped_column()
    hp_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Стройка пристройки (один слот за раз)
    build_item: Mapped[str | None] = mapped_column(String(32))
    build_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Возвращалка: last_seen_at — любое действие игрока (трогает middleware);
    # nudge_tier — какая ступень напоминания о простое уже отправлена (0/1/2/3),
    # сбрасывается в 0 при активности.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nudge_tier: Mapped[int] = mapped_column(default=0)

    # Ежедневный бонус («опохмел»): claimable-предложение (bonus_kind) висит 24ч
    # и сгорает; активный баф (buff_kind) действует 4ч; bonus_next_at — когда
    # разрешено выдать следующее предложение (раз в сутки).
    bonus_kind: Mapped[str | None] = mapped_column(String(16))
    bonus_offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    buff_kind: Mapped[str | None] = mapped_column(String(16))
    buff_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bonus_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Живой город: память игрока — флаги-факты, отношения с NPC, репутация
    # фракций, текущее событие на решении (pending) и очередь отложенных (queue).
    story: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Лимит покупки на бирже (анти-абуз, как buy-limit в RuneScape): сколько
    # каждого товара куплено в текущем 4-часовом окне. {good: {"t": iso, "q": n}}.
    bourse_buys: Mapped[dict] = mapped_column(JSONB, default=dict)

    tavern: Mapped["Tavern | None"] = relationship(
        back_populates="player", uselist=False, lazy="selectin"
    )


class WorldState(Base):
    """Глобальное состояние мира (одна строка id=1): мировые события."""

    __tablename__ = "world"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    fair_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_fair_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Анонс ближайшей ярмарки уже отправлен в чаты (сброс при её открытии).
    fair_pre_announced: Mapped[bool] = mapped_column(default=False)
    # Последний анонсированный сезон/праздник (дедуп рассылки смены).
    season: Mapped[int] = mapped_column(default=-1)
    holiday: Mapped[str | None] = mapped_column(String(48))
    # Дата (МСК, YYYY-MM-DD) последней утренней рассылки «бонус готов» — дедуп.
    bonus_push_on: Mapped[str | None] = mapped_column(String(10))
    # ЕДИНЫЙ глобальный рынок (общий для всех чатов): оптовый завал/дефицит по
    # товарам — {good: glut_units, '_t': метка распада}. Двигают его ВСЕ сделки
    # мира (сбыт купцам, NPC-аукцион, P2P-биржа), цена одна для всех.
    market: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Масштаб рынка = число активных чатов (нотифаер обновляет раз в тик). Пороги
    # насыщения/дефицита множатся на него: реактивность цены держится как у одного
    # чата при любом размере мира (нормировка по интенсивности, не по объёму).
    market_scale: Mapped[int] = mapped_column(default=1)
    # Кэш Telegram file_id статичных картинок/видео: {"имя:размер": file_id}.
    # Переживает деплой (ФС Railway эфемерна) → медиа не грузятся заново каждый раз.
    media_ids: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Время последней биржевой сводки в чаты (дайджест новых лотов раз в N минут).
    bourse_announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnownChat(Base):
    """Общий чат, где бот замечен в деле, — адресат анонсов мировых событий."""

    __tablename__ = "chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(128))
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CityState(Base):
    """Живой город — свой на каждый Telegram-чат (общий мир его участников)."""

    __tablename__ = "cities"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mood: Mapped[int] = mapped_column(default=0)            # настроение города
    faction_power: Mapped[dict] = mapped_column(JSONB, default=dict)  # {фракция: сила}
    situations: Mapped[list] = mapped_column(JSONB, default=list)     # [{id, faction, until}]
    # Динамический рынок: {товар: завал, '_t': метка распада} — оптовая цена
    # проседает от сбыта и впитывается спросом со временем.
    market: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_situation_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LootDrop(Base):
    """Подкидыш в общий чат: что-то «потерялось». Кто первый нажал — подобрал
    (claimed_by). Исход роллится при подборе; строка нужна для гонки «кто первый»."""

    __tablename__ = "loot_drops"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    claimed_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MarketOrder(Base):
    """Лот ЕДИНОЙ (глобальной) биржи. side='sell' — владелец продаёт (товар
    заморожен в погребе); side='buy' — владелец покупает (золото qty*unit_price
    в эскроу). seller_id — id владельца-создателя лота. Скоуп ГЛОБАЛЬНЫЙ: стакан
    общий для всех чатов, сведение идёт по всему миру. chat_id — лишь «источник»
    (откуда выставлен), для аналитики; на матчинг не влияет."""

    __tablename__ = "market_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)  # источник (аналитика)
    seller_id: Mapped[int] = mapped_column(BigInteger, index=True)  # владелец лота
    side: Mapped[str] = mapped_column(String(8), default="sell")    # 'sell' | 'buy'
    good: Mapped[str] = mapped_column(String(16))
    qty: Mapped[int] = mapped_column()
    unit_price: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Notification(Base):
    """Отложенная личка игроку (outbox): кладём атомарно со сделкой, нотифаер
    разбирает и шлёт — без сетевых вызовов под локами строк."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    text: Mapped[str] = mapped_column(String(1024))
    photo: Mapped[str | None] = mapped_column(String(256))  # file_id картинки (рассылка)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RaidBoss(Base):
    """Глобальный рейд-босс (один живой на весь мир). Две фазы:
      gathering — 20 мин сбор: игроки регистрируются, идёт обратный отсчёт;
      active    — битва ~1ч: записавшиеся бьют, HP — единый источник правды.
    Далее dead (повержен) / expired (ушёл/никто не пришёл).

    contributions: {str(player_id): {"dmg": int, "hits": int, "last": iso,
    "name": str}} — запись (dmg=0 при регистрации), потом копит урон.
    messages: {str(chat_id): message_id} — сообщения-анонсы в чатах (правим
    текст: отсчёт сбора → HP-бар битвы)."""

    __tablename__ = "raid_boss"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    boss_key: Mapped[str] = mapped_column(String(32))
    max_hp: Mapped[int] = mapped_column(default=0)   # ставится при старте битвы
    hp: Mapped[int] = mapped_column(default=0)
    contributions: Mapped[dict] = mapped_column(JSONB, default=dict)
    messages: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Боевое состояние: {stun_until, last_roar, second_wind} — рык/реген/второе дыхание.
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="gathering")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    gather_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LogEntry(Base):
    """Журнал событий: действия игроков и админа (для админ-панели)."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)  # 'player' | 'admin'
    actor_id: Mapped[int] = mapped_column(BigInteger, index=True)  # кто (игрок/админ)
    text: Mapped[str] = mapped_column(String(512))


class Chronicle(Base):
    """Летопись города: лента заметных событий для экрана «Хроника»."""

    __tablename__ = "chronicle"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    text: Mapped[str] = mapped_column(String(256))


class Tavern(Base):
    """Таверна игрока (одна на игрока)."""

    __tablename__ = "taverns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.id"), unique=True
    )

    name: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(default=1)
    capacity: Mapped[int] = mapped_column(default=10)
    comfort: Mapped[int] = mapped_column(default=1)
    income_rate: Mapped[int] = mapped_column(default=10)  # золото в час
    reputation: Mapped[int] = mapped_column(default=0)

    upgrades: Mapped[dict] = mapped_column(JSONB, default=dict)
    buildings: Mapped[list] = mapped_column(JSONB, default=list)
    production: Mapped[dict] = mapped_column(JSONB, default=dict)  # партии зданий
    products: Mapped[dict] = mapped_column(JSONB, default=dict)    # погреб: {ярус: эль}
    # Аукцион: один активный лот {good, qty, unit_min, ends_at, top_bid,
    # top_bidder, bids, history} — товар заморожен в лоте.
    auction: Mapped[dict] = mapped_column(JSONB, default=dict)

    last_income_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    map_slot: Mapped[int | None] = mapped_column(unique=True)

    player: Mapped[Player] = relationship(back_populates="tavern")
