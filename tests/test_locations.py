from app.city_codes import city_label
from app.locations import search_locations
from app.services.locations import resolve_location_code, resolve_route_location, should_offer_location_choices


def test_resolve_location_code_accepts_city_airport_and_label() -> None:
    assert resolve_location_code("MOW") == "MOW"
    assert resolve_location_code("Шереметьево") == "MOW"
    assert resolve_location_code("Москва, Шереметьево — SVO") == "MOW"
    assert resolve_location_code("Кольцово") == "SVX"
    assert resolve_location_code("КЛЦ") == "SVX"


def test_resolve_route_location_keeps_airport_as_filter() -> None:
    svo = resolve_route_location("Москва, Шереметьево — SVO")
    svx = resolve_route_location("Кольцово")

    assert svo is not None
    assert svo.code == "MOW"
    assert svo.airport_code == "SVO"
    assert svx is not None
    assert svx.code == "SVX"
    assert svx.airport_code == "SVX"


def test_resolve_location_code_rejects_unknown_text() -> None:
    assert resolve_location_code("непонятное место") is None


def test_location_search_uses_russian_airports_data() -> None:
    choices = search_locations("Москва", limit=5)

    assert [item["value"] for item in choices[:4]] == ["MOW", "SVO", "DME", "VKO"]
    assert search_locations("Шереметьево", limit=1)[0]["value"] == "SVO"
    assert search_locations("Кольцово", limit=1)[0]["value"] == "SVX"


def test_location_choice_offer_for_moscow() -> None:
    assert should_offer_location_choices("Москва") is True


def test_telegram_location_helpers_use_shared_resolver() -> None:
    from app.telegram_bot import location_choices, resolve_location, should_offer_location_choices as bot_should_offer

    choices = location_choices("Москва")

    assert ("Москва — все аэропорты — MOW", "MOW") in choices
    assert resolve_location("Москва, Шереметьево — SVO") == "MOW"
    assert bot_should_offer("Москва") is True


def test_city_label_uses_airports_data_for_new_codes() -> None:
    assert city_label("REN") == "Оренбург"
