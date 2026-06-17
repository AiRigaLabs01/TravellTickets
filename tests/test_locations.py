from app.services.locations import resolve_location_code, should_offer_location_choices


def test_resolve_location_code_accepts_city_airport_and_label() -> None:
    assert resolve_location_code("MOW") == "MOW"
    assert resolve_location_code("Шереметьево") == "SVO"
    assert resolve_location_code("Москва, Шереметьево — SVO") == "SVO"


def test_resolve_location_code_rejects_unknown_text() -> None:
    assert resolve_location_code("непонятное место") is None


def test_location_choice_offer_for_moscow() -> None:
    assert should_offer_location_choices("Москва") is True


def test_telegram_location_helpers_use_shared_resolver() -> None:
    from app.telegram_bot import location_choices, resolve_location, should_offer_location_choices as bot_should_offer

    choices = location_choices("Москва")

    assert ("Москва — все аэропорты — MOW", "MOW") in choices
    assert resolve_location("Москва, Шереметьево — SVO") == "SVO"
    assert bot_should_offer("Москва") is True
