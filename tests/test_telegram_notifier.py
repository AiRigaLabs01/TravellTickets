from types import SimpleNamespace

from app.telegram_notifier import build_debug_monitoring_text, build_no_changes_text


def _route() -> SimpleNamespace:
    return SimpleNamespace(
        origin="SVX",
        destination="MOW",
        departure_date="2026-06-20",
        interval_minutes=10,
        max_price=4500,
    )


def test_no_changes_text_uses_all_conditions_label() -> None:
    text = build_no_changes_text(_route(), flights_count=3, filtered_count=0, best_flight=None)

    assert "Найдено API: 3" in text
    assert "Подходящих под все условия: 0" in text
    assert "После фильтров по лимиту" not in text


def test_debug_text_uses_all_conditions_label() -> None:
    text = build_debug_monitoring_text(_route(), flights_count=3, filtered_count=0, best_flight=None)

    assert "Найдено API: 3" in text
    assert "Подходящих под все условия: 0" in text
    assert "После фильтров по лимиту" not in text
