from app.services.locations import resolve_location_code, should_offer_location_choices


def test_resolve_location_code_accepts_city_airport_and_label() -> None:
    assert resolve_location_code("MOW") == "MOW"
    assert resolve_location_code("Шереметьево") == "SVO"
    assert resolve_location_code("Москва, Шереметьево — SVO") == "SVO"


def test_resolve_location_code_rejects_unknown_text() -> None:
    assert resolve_location_code("непонятное место") is None


def test_location_choice_offer_for_moscow() -> None:
    assert should_offer_location_choices("Москва") is True
