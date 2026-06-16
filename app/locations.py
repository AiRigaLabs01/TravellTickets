from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    label: str
    value: str
    type: str
    city: str
    keywords: tuple[str, ...]


LOCATIONS: list[Location] = [
    Location("Екатеринбург — SVX", "SVX", "city", "Екатеринбург", ("екатеринбург", "свердловск", "svx", "кольцово")),
    Location("Москва — все аэропорты — MOW", "MOW", "city", "Москва", ("москва", "мск", "мow", "mow", "все аэропорты")),
    Location("Москва, Шереметьево — SVO", "SVO", "airport", "Москва", ("москва", "шереметьево", "svo", "sheremetyevo")),
    Location("Москва, Внуково — VKO", "VKO", "airport", "Москва", ("москва", "внуково", "vko", "vnukovo")),
    Location("Москва, Домодедово — DME", "DME", "airport", "Москва", ("москва", "домодедово", "dme", "domodedovo")),
    Location("Москва, Жуковский — ZIA", "ZIA", "airport", "Москва", ("москва", "жуковский", "zia", "zhukovsky")),
    Location("Санкт-Петербург — LED", "LED", "city", "Санкт-Петербург", ("санкт-петербург", "петербург", "питер", "спб", "led", "пулково")),
    Location("Сочи — AER", "AER", "city", "Сочи", ("сочи", "aer", "адлер")),
    Location("Казань — KZN", "KZN", "city", "Казань", ("казань", "kzn")),
    Location("Новосибирск — OVB", "OVB", "city", "Новосибирск", ("новосибирск", "ovb", "толмачево", "толмачёво")),
    Location("Минеральные Воды — MRV", "MRV", "city", "Минеральные Воды", ("минеральные воды", "минводы", "mrv")),
    Location("Калининград — KGD", "KGD", "city", "Калининград", ("калининград", "kgd", "храброво")),
    Location("Самара — KUF", "KUF", "city", "Самара", ("самара", "kuf")),
    Location("Уфа — UFA", "UFA", "city", "Уфа", ("уфа", "ufa")),
    Location("Пермь — PEE", "PEE", "city", "Пермь", ("пермь", "pee")),
    Location("Тюмень — TJM", "TJM", "city", "Тюмень", ("тюмень", "tjm")),
    Location("Челябинск — CEK", "CEK", "city", "Челябинск", ("челябинск", "cek")),
    Location("Нижний Новгород — GOJ", "GOJ", "city", "Нижний Новгород", ("нижний новгород", "goj")),
]


POPULAR_ORIGINS = [
    ("Екатеринбург / SVX", "SVX"),
    ("Москва / MOW", "MOW"),
    ("Санкт-Петербург / LED", "LED"),
    ("Сочи / AER", "AER"),
]

POPULAR_DESTINATIONS = [
    ("Москва / MOW", "MOW"),
    ("Санкт-Петербург / LED", "LED"),
    ("Сочи / AER", "AER"),
    ("Казань / KZN", "KZN"),
]


def search_locations(query: str, limit: int = 10) -> list[dict[str, str]]:
    q = (query or "").strip().lower()
    if not q:
        matches = LOCATIONS[:limit]
    else:
        matches = [
            loc for loc in LOCATIONS
            if q in loc.label.lower() or any(q in kw.lower() for kw in loc.keywords)
        ][:limit]
    return [
        {"label": loc.label, "value": loc.value, "type": loc.type, "city": loc.city}
        for loc in matches
    ]
