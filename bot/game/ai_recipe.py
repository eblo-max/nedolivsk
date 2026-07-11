"""«Тайные рецепты» — тонкий слой Claude поверх детерминированного ядра (recipes.py).

ИИ придумывает ТОЛЬКО флейвор (имя/лор) и ПРЕДЛАГАЕТ веса эффектов из белого списка.
Числа назначает `recipes.assign_effects` (кламп бюджетом) — не ИИ. Любой сбой (нет
ключа, отказ классификатора, сетевая ошибка, чужая версия SDK) → возвращаем None,
вызывающий строит рецепт процедурно (`recipes.build_recipe` без ai_*). Игра не падает
никогда. Ключ — только из Railway-env (`settings.anthropic_api_key`), не логируется.

Проверить живой вызов нужно один раз ПОСЛЕ добавления ANTHROPIC_API_KEY в Railway
(до этого фича идёт процедурным путём — это ожидаемо и покрыто тестами с моком).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

from bot.config import settings
from bot.game import balance, recipes

log = logging.getLogger(__name__)

# SDK может быть ещё не установлен локально — импорт под guard, чтобы модуль грузился.
try:  # pragma: no cover - зависит от окружения
    import anthropic
    from anthropic import AsyncAnthropic
except Exception:  # noqa: BLE001
    anthropic = None
    AsyncAnthropic = None

MODEL = "claude-haiku-4-5"       # дёшево/быстро для массовой простой задачи «флейвор»
MAX_TOKENS = 600
NAME_MAX = 60
LORE_MAX = 220

_client = None


class AIEffects(BaseModel):
    """Веса эффектов 0..5 (0 = нет). Конкретные поля — чтобы модель их РЕАЛЬНО
    заполняла (свободный dict она возвращала пустым). Величины назначит код."""
    model_config = ConfigDict(extra="ignore")
    dmg: float = 0
    crit: float = 0
    dodge: float = 0
    hp: float = 0
    antidote: float = 0


class AIRecipe(BaseModel):
    """Структурированный ответ ИИ. effects — ПРЕДЛОЖЕНИЕ весов; числа переназначит код."""
    name: str
    lore: str
    effects: AIEffects


def available() -> bool:
    """ИИ реально можно вызвать (SDK установлен И ключ задан). Иначе — процедурный путь."""
    return bool(anthropic and AsyncAnthropic and settings.anthropic_api_key)


def _get_client():
    global _client
    if _client is None:
        # httpx-транспорт по умолчанию (идёт зависимостью с anthropic). aiohttp-клиент
        # (DefaultAioHttpClient) требует экстры anthropic[aiohttp] и без неё падал
        # RuntimeError; httpx-async работает в том же event-loop, что aiogram/aiohttp.
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _catalog() -> str:
    """Каталог съедобных ингредиентов с русскими именами и вкусовыми тегами — из
    ядра, чтобы промпт не рассинхронился с игрой."""
    lines = []
    for k in recipes.INGREDIENTS:
        name = balance.RESOURCE_NAMES.get(k, k)
        tags = ", ".join(recipes.INGREDIENT_TAGS.get(k, ()))
        lines.append(f"- {k} ({name}): {tags}")
    return "\n".join(lines)


# Стабильный system-префикс (кэшируется). Правила + каталог + белый список + примеры.
SYSTEM = f"""Ты — повар средневековой корчмы в городе Недоливск. Игрок принёс горсть
ингредиентов, а ты придумываешь из них ТАЙНЫЙ фирменный рецепт: колоритное название,
короткий сочный лор и НАБОР эффектов.

ВЕРНИ строго JSON с полями:
- name: название блюда (до {NAME_MAX} символов), средневеково-трактирный тон, можно
  с прозвищем («Похмельный борщ боярина Твердислава»). Без пошлости, жестокости,
  реальных людей и политики.
- lore: 1-2 предложения атмосферного описания (до {LORE_MAX} символов).
- effects: объект с полями dmg/crit/dodge/hp/antidote — относительный вес 0..5
  (0 = эффекта нет). ОБЯЗАТЕЛЬНО заполни 1–3 поля НЕНУЛЕВЫМИ по вкусу ингредиентов
  (см. теги), остальные оставь 0. Это ПОДСКАЗКА балансу — итоговые числа назначит
  игра из бюджета; ты задаёшь только НАПРАВЛЕНИЕ (какие эффекты и их соотношение).

Белый список эффектов (и к чему тяготеет вкус):
- dmg  — урон в бою (острое, пряное, солёное)
- crit — шанс крита (хмельное/бродящее, сладкое, горькое)
- dodge — уворот (травяное, кислое)
- hp   — здоровье на бой (сытное, жирное, мучное, молочное)
- antidote — снимает яд/проклятье (травяное, кислое молоко)

Каталог ингредиентов (ключ, имя, теги вкуса):
{_catalog()}

Примеры (формат, не копируй дословно):
{{"name": "Похмельный взвар деда Пафнутия", "lore": "Тёмное варево из хмеля и солода — с одной кружки в глазах двоится, а рука в драке тверда.", "effects": {{"crit": 3, "hp": 1}}}}
{{"name": "Огневая солянка «У плахи»", "lore": "Наперчено так, что палач слезу пустил. Пьёшь — и кулаки сами тянутся к драке.", "effects": {{"dmg": 4}}}}
"""


def _clean(s: str | None, maxlen: int) -> str:
    """Модерация текста код-сайд: срез управляющих символов, схлопывание пробелов,
    лимит длины. (HTML-escape — на слое показа: чат/мини-апп.)"""
    s = "".join(ch for ch in (s or "") if ch >= " " or ch == "\n")
    s = " ".join(s.split()).strip()
    return s[:maxlen].strip()


async def invent(ingredients: list[str], budget: int) -> tuple[str, str, dict] | None:
    """Спросить ИИ имя/лор/веса. Возвращает (name, lore, proposal) или None → фолбэк.
    `ingredients` уже провалидированы вызывающим (recipes.valid_combo) — свободного
    текста в модель не уходит, только ключи из словаря (анти-инъекция)."""
    if not available():
        return None
    names = [f"{k} ({balance.RESOURCE_NAMES.get(k, k)})" for k in sorted(set(ingredients))]
    try:
        r = await _get_client().messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user",
                       "content": f"Ингредиенты: {', '.join(names)}. "
                                  f"Ориентир силы (бюджет очков): {budget}."}],
            output_format=AIRecipe,
        )
        if getattr(r, "stop_reason", None) == "refusal":   # классификатор отказал
            log.info("ai_recipe: refusal, using procedural fallback")
            return None
        out: AIRecipe = r.parsed_output
    except Exception as e:  # noqa: BLE001 — сеть/429/5xx/иная версия SDK → фолбэк
        log.warning("ai_recipe.invent failed (%s), using procedural fallback", type(e).__name__)
        return None

    name = _clean(out.name, NAME_MAX)
    lore = _clean(out.lore, LORE_MAX)
    # веса из именованных полей (только ненулевые); величины всё равно назначит ядро
    proposal = {k: float(getattr(out.effects, k)) for k in recipes.ALLOWED_EFFECTS
                if float(getattr(out.effects, k)) > 0}
    return name, lore, proposal
