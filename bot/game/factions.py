"""Фракции Недоливска. Репутация фракций — на игроке (story.faction),
сила фракций в городе — на CityState.faction_power."""

NAMES: dict[str, str] = {
    "watch": "Стража",
    "thieves": "Воровская гильдия",
    "merchants": "Купеческая лига",
    "church": "Церковь",
    "crown": "Корона",
}


def name(fac_id: str) -> str:
    return NAMES.get(fac_id, fac_id)
