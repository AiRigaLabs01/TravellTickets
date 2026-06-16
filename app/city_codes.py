CITY_TO_IATA: dict[str, str] = {
    "екатеринбург": "SVX",
    "свердловск": "SVX",
    "москва": "MOW",
    "мск": "MOW",
    "санкт-петербург": "LED",
    "питер": "LED",
    "спб": "LED",
    "петербург": "LED",
    "сочи": "AER",
    "казань": "KZN",
    "новосибирск": "OVB",
    "минеральные воды": "MRV",
    "минводы": "MRV",
    "калининград": "KGD",
    "краснодар": "KRR",
    "самара": "KUF",
    "уфа": "UFA",
    "пермь": "PEE",
    "тюмень": "TJM",
    "челябинск": "CEK",
    "красноярск": "KJA",
    "иркутск": "IKT",
    "хабаровск": "KHV",
    "владивосток": "VVO",
    "нижний новгород": "GOJ",
    "ростов": "ROV",
    "ростов-на-дону": "ROV",
    "воронеж": "VOZ",
    "омск": "OMS",
    "анапа": "AAQ",
    "симферополь": "SIP",
    "мурманск": "MMK",
    "архангельск": "ARH",
    "астрахань": "ASF",
    "волгоград": "VOG",
    "саратов": "RTW",
    "барнаул": "BAX",
    "томск": "TOF",
    "кемерово": "KEJ",
    "якутск": "YKS",
    "махачкала": "MCX",
    "ставрополь": "STW",
    "оренбург": "REN",
    "шереметьево": "SVO",
    "домодедово": "DME",
    "внуково": "VKO",
    "жуковский": "ZIA",
}

AIRLINE_NAMES: dict[str, str] = {
    "SU": "Аэрофлот",
    "DP": "Победа",
    "S7": "S7 Airlines",
    "U6": "Уральские авиалинии",
    "N4": "Nordwind",
    "5N": "Smartavia",
    "FV": "Россия",
    "UT": "ЮТэйр",
    "6R": "Алроса",
    "YC": "Якутия",
}

AIRPORT_NAMES: dict[str, str] = {
    "SVO": "Шереметьево",
    "DME": "Домодедово",
    "VKO": "Внуково",
    "ZIA": "Жуковский",
    "SVX": "Екатеринбург",
    "LED": "Пулково",
    "AER": "Сочи",
    "KZN": "Казань",
    "OVB": "Новосибирск",
    "MRV": "Минеральные Воды",
    "KGD": "Калининград",
}

MOSCOW_AIRPORTS = ["SVO", "DME", "VKO", "ZIA"]

IATA_TO_CITY: dict[str, str] = {
    "SVX": "Екатеринбург",
    "MOW": "Москва",
    "LED": "Санкт-Петербург",
    "AER": "Сочи",
    "KZN": "Казань",
    "OVB": "Новосибирск",
    "MRV": "Минеральные Воды",
    "KGD": "Калининград",
    "SVO": "Москва (Шереметьево)",
    "DME": "Москва (Домодедово)",
    "VKO": "Москва (Внуково)",
    "ZIA": "Москва (Жуковский)",
    "KRR": "Краснодар",
    "KUF": "Самара",
    "UFA": "Уфа",
    "PEE": "Пермь",
    "TJM": "Тюмень",
    "CEK": "Челябинск",
    "KJA": "Красноярск",
    "IKT": "Иркутск",
    "KHV": "Хабаровск",
    "VVO": "Владивосток",
    "GOJ": "Нижний Новгород",
    "ROV": "Ростов-на-Дону",
    "VOZ": "Воронеж",
    "OMS": "Омск",
}


def resolve_iata(value: str) -> str:
    """Convert a city name or IATA code string to an IATA code."""
    v = value.strip()
    if len(v) == 3 and v.isalpha():
        return v.upper()
    lookup = v.lower()
    return CITY_TO_IATA.get(lookup, v.upper())


def city_label(iata: str) -> str:
    """Return a human-readable label for an IATA code."""
    return IATA_TO_CITY.get(iata.upper(), iata.upper())


def airline_label(code: str) -> str:
    return AIRLINE_NAMES.get(code.strip().upper(), code.strip().upper())


def airport_label(code: str) -> str:
    return AIRPORT_NAMES.get(code.strip().upper(), code.strip().upper())
