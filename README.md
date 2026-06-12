# 🍺 Недоливск

Telegram-бот с текстовой многопользовательской игрой: симулятор средневековой таверны на inline-кнопках.

## Что уже есть (MVP, итерация 1)

- Регистрация игрока и создание таверны (название + выбор региона)
- Экран таверны: уровень, вместимость, комфорт, доход, репутация, запасы
- Сбор ресурсов по кулдауну (30 мин): древесина, зерно, хмель; бонус региона
- Пассивный доход золотом (копится до 8 часов)
- Улучшение таверны до 10 уровня (рост параметров и репутации)
- Заглушка для группового чата (отправляет в личку)

## Запуск

1. **Токен бота.** Напишите [@BotFather](https://t.me/BotFather) → `/newbot` → задайте имя и username бота → скопируйте токен.

2. **Конфигурация:**
   ```bash
   cp .env.example .env
   # вставьте токен в BOT_TOKEN
   ```

3. **База данных** (нужен Docker):
   ```bash
   docker compose up -d
   ```

4. **Зависимости и запуск:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -r requirements.txt
   python -m bot.main
   ```

Таблицы создаются автоматически при первом старте.

## Структура

```
bot/
├── main.py           # точка входа, polling
├── config.py         # настройки из .env
├── texts.py          # все игровые тексты
├── middlewares.py    # сессия БД на каждый апдейт
├── db/
│   ├── base.py       # engine, сессии
│   ├── models.py     # Player, Tavern
│   └── repo.py       # запросы
├── game/
│   ├── balance.py    # весь игровой баланс (числа)
│   └── logic.py      # механики: сбор, доход, улучшение
├── handlers/
│   ├── start.py      # регистрация, создание таверны
│   ├── tavern.py     # экран таверны и действия
│   └── group.py      # общий чат (пока заглушка)
└── keyboards/
    └── inline.py     # inline-клавиатуры
```

## Деплой (Railway / Render)

Бот работает в режиме polling — публичный URL не нужен, подойдёт worker-сервис.

**Railway** (проще всего):
1. Запушьте репозиторий на GitHub.
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub repo (Railway сам соберёт Dockerfile).
3. В том же проекте: Create → Database → PostgreSQL.
4. В сервисе бота → Variables:
   - `BOT_TOKEN` — токен от @BotFather
   - `DATABASE_URL` — Add Reference → выбрать `DATABASE_URL` из Postgres
5. Deploy. Готово — бот онлайн 24/7.

**Render**:
1. [render.com](https://render.com) → New → Background Worker → подключить GitHub-репозиторий (runtime: Docker).
2. New → PostgreSQL, скопировать Internal Database URL.
3. В worker → Environment: `BOT_TOKEN`, `DATABASE_URL`.

Конфиг сам преобразует `postgres://` из облака в нужный формат `postgresql+asyncpg://`.

## Дорожная карта

1. ✅ Ядро: таверна, ресурсы, улучшения
2. Пристройки (пивоварня, конюшня, погреб) и крафт товаров
3. Общий чат: мировые события, новости, рейтинг таверн
4. Взаимодействие игроков: визиты, торговля
5. Статичные изображения экранов

Баланс игры целиком в `bot/game/balance.py` — крутить числа можно без правки логики.
