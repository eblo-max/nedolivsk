"""Реестр граждан Недоливска. Общие для чата персонажи живого города."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Npc:
    id: str
    name: str
    emoji: str
    faction: str | None = None  # к какой фракции тяготеет


CATALOG: dict[str, Npc] = {
    "buhlo": Npc("buhlo", "Сир Бухло", "🛡"),
    "mzdoimov": Npc("mzdoimov", "Капитан Мздоимов", "👮", "watch"),
    "lutik": Npc("lutik", "Бард Лютик", "🎻"),
    "paraska": Npc("paraska", "Вдова Параска", "🧹"),
    "skupshik": Npc("skupshik", "Скупщик", "🥷", "thieves"),
    "alchemist": Npc("alchemist", "Безумный Алхимик", "⚗️"),
    "magnat": Npc("magnat", "Купец Толстосумов", "💰", "merchants"),
    "vedma": Npc("vedma", "Ведьма Гнилозубка", "🔮"),
    "kartavy": Npc("kartavy", "Картёжник Картавый", "🎲"),
}


def get(npc_id: str) -> Npc | None:
    return CATALOG.get(npc_id)


def label(npc_id: str) -> str:
    n = CATALOG.get(npc_id)
    return f"{n.emoji} {n.name}" if n else npc_id
