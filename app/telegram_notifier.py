import logging
import asyncio
from datetime import datetime
from typing import Any

from app.config import TELEGRAM_BOT_TOKEN
from app.date_utils import format_msk_time, format_route_date_long

logger = logging.getLogger(__name__)


def _format_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    if h and m:
        return f"{h}ч {m}м"
    if h:
        return f"{h}ч"
    return f"{m}м"


def _fmt_dt(dt: datetime | None) -> str:
    return format_msk_time(dt)


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return format_route_date_long(dt.date().isoformat())


def _airline_name(code: str) -> str:
    from app.city_codes import AIRLINE_NAMES
    name = AIRLINE_NAMES.get((code or "").upper(), "")
    return f"{name} ({code})" if name else code


def _city_label(iata: str) -> str:
    from app.city_codes import IATA_TO_CITY
    name = IATA_TO_CITY.get((iata or "").upper(), "")
    return f"{name} ({iata})" if name else iata


def _short_route(route: Any) -> str:
    return f"{_city_label(route.origin)} → {_city_label(route.destination)}"


def _append_yandex_link(lines: list[str], yandex_url: str | None):
    if yandex_url:
        lines.append("")
        lines.append(f"🔗 <a href='{yandex_url}'>Проверить на Яндекс Путешествиях</a>")


def _append_aviasales_link(lines: list[str], flight: dict):
    aviasales_url = flight.get("telegram_aviasales_url") or flight.get("aviasales_url")
    if aviasales_url:
        lines.append("")
        lines.append(f"✈️ <a href='{aviasales_url}'>Посмотреть билет на Aviasales</a>")


def _seller_line(flight: dict) -> str:
    return f"🏷 Продавец: {flight.get('gate') or '—'}"


def _leg_lines(title: str, leg: dict) -> list[str]:
    return [
        f"<b>{title}</b>",
        f"✈️ Рейс: {leg.get('airline', '—')} {leg.get('flight_number', '')}",
        f"🏢 Аэропорт: {leg.get('origin_airport', leg.get('origin', '—'))} → {leg.get('destination_airport', leg.get('destination', '—'))}",
        f"🛫 Вылет: {_fmt_dt(leg.get('departure_at'))}",
        f"🛬 Прилёт: {_fmt_dt(leg.get('estimated_arrival_at'))}, рассчитано",
        _seller_line(leg),
        f"💵 Цена плеча: {int(leg.get('price', 0)):,} ₽".replace(",", " "),
    ]


def build_notification_text(route: Any, flight: dict) -> str:
    return_flight = flight.get("return_flight")
    if return_flight:
        lines = [
            "🔥 <b>Найден билет туда-обратно по вашим условиям</b>",
            _short_route(route),
            f"💰 Общая цена: <b>{int(flight.get('price', 0)):,} ₽</b>".replace(",", "\u00a0"),
            f"🎯 Ваш лимит: {int(route.max_price):,} ₽".replace(",", " "),
            "",
        ]
        lines.extend(_leg_lines("Туда", flight))
        lines.append("")
        lines.extend(_leg_lines("Обратно", return_flight))
        _append_aviasales_link(lines, flight)
        _append_yandex_link(lines, flight.get("yandex_travel_url"))
        lines.append("\n<i>⚠️ Цена туда-обратно рассчитана как сумма двух отдельных плеч из кэша Aviasales. Финальную цену и тариф проверяйте у продавца.</i>")
        return "\n".join(lines)

    dep_dt = flight.get("departure_at")
    arr_dt = flight.get("estimated_arrival_at")
    duration = flight.get("duration", 0) or 0
    arrival_note = ", рассчитано" if flight.get("is_estimated_arrival") else ""
    transfers = flight.get("transfers", 0)
    transfers_str = "нет" if transfers == 0 else str(transfers)

    lines = [
        "🔥 <b>Найден билет по вашим условиям</b>\n",
        _short_route(route),
        f"{_fmt_date(dep_dt)}\n",
        f"💰 Цена: <b>{int(flight.get('price', 0)):,} ₽</b>".replace(",", "\u00a0"),
        f"✈️ Рейс: {_airline_name(flight.get('airline', ''))} {flight.get('flight_number', '')}",
        f"🏢 Аэропорт: {flight.get('origin_airport', route.origin)} → {flight.get('destination_airport', route.destination)}",
        f"🛫 Вылет: {_fmt_dt(dep_dt)}",
        f"🛬 Прилёт: {_fmt_dt(arr_dt)}{arrival_note}",
    ]
    if duration:
        lines.append(f"⏱ В пути: {_format_duration(duration)}")
    lines.append(f"🔀 Пересадки: {transfers_str}")
    lines.append(_seller_line(flight))

    _append_aviasales_link(lines, flight)
    _append_yandex_link(lines, flight.get("yandex_travel_url"))
    lines.append("\n<i>⚠️ Цены из кэша Aviasales — уточняйте актуальную цену у продавца перед покупкой.</i>")
    return "\n".join(lines)


def _best_flight_lines(route: Any, flight: dict) -> list[str]:
    price = int(flight.get("price", 0))
    lines = []
    if flight.get("above_limit"):
        diff = price - int(route.max_price)
        lines.append("<b>Минимальная найденная цена выше вашего лимита</b>")
        lines.append(f"💵 Найдено: {price:,} ₽".replace(",", " "))
        lines.append(f"🎯 Ваш лимит: {int(route.max_price):,} ₽".replace(",", " "))
        if diff > 0:
            lines.append(f"↗️ Выше лимита на {diff:,} ₽".replace(",", " "))
    else:
        lines.append("<b>Текущий лучший вариант</b>")
        lines.append(f"💵 Цена: {price:,} ₽".replace(",", " "))
    if flight.get("return_flight"):
        lines.append("")
        lines.extend(_leg_lines("Туда", flight))
        lines.append("")
        lines.extend(_leg_lines("Обратно", flight["return_flight"]))
    else:
        lines.extend([
            f"✈️ Рейс: {flight.get('airline', '—')} {flight.get('flight_number', '')}",
            f"🕓 Вылет: {_fmt_dt(flight.get('departure_at'))}",
            f"🕕 Прилёт: {_fmt_dt(flight.get('estimated_arrival_at'))}, рассчитано",
            _seller_line(flight),
        ])
    return lines


def build_no_changes_text(route: Any, flights_count: int, filtered_count: int, best_flight: dict | None) -> str:
    checked_at = format_msk_time(datetime.utcnow())
    lines = [
        "✅ <b>Изменений за период не было</b>",
        f"🔄 Проверено: {checked_at}",
        f"🛫 Маршрут: {_short_route(route)}",
        f"📅 Дата: {format_route_date_long(route.departure_date)}",
        f"⏱ Период: {route.interval_minutes} мин",
        "",
        f"Найдено API: {flights_count}",
        f"Подходящих под все условия: {filtered_count}",
    ]
    if best_flight:
        lines.append("")
        lines.extend(_best_flight_lines(route, best_flight))
        _append_aviasales_link(lines, best_flight)
        _append_yandex_link(lines, best_flight.get("yandex_travel_url"))
    else:
        lines.append("Подходящих билетов по условиям не найдено.")
    lines.append("")
    lines.append("Новых подходящих цен или улучшений не появилось.")
    return "\n".join(lines)


def build_debug_monitoring_text(route: Any, flights_count: int, filtered_count: int, best_flight: dict | None, error: str | None = None) -> str:
    checked_at = format_msk_time(datetime.utcnow())
    lines = [
        "🧪 <b>Отладка мониторинга</b>",
        f"🔄 Проверка выполнена: {checked_at}",
        f"🛫 Маршрут: {_short_route(route)}",
        f"📅 Дата: {format_route_date_long(route.departure_date)}",
        f"💰 Порог: {int(route.max_price):,} ₽".replace(",", " "),
        f"⏱ Интервал: {route.interval_minutes} мин",
        "",
    ]
    if error:
        lines.append(f"⚠️ Ошибка API/проверки: {error}")
    else:
        lines.append(f"Найдено API: {flights_count}")
        lines.append(f"Подходящих под все условия: {filtered_count}")
        if best_flight:
            lines.append("")
            lines.extend(_best_flight_lines(route, best_flight))
            _append_aviasales_link(lines, best_flight)
            _append_yandex_link(lines, best_flight.get("yandex_travel_url"))
        else:
            lines.append("Подходящих билетов по условиям не найдено.")
    lines.append("")
    lines.append(f"Следующая проверка: примерно через {route.interval_minutes} мин")
    return "\n".join(lines)


async def send_telegram_notification(chat_id: str, text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not configured, skipping notification")
        return False
    if not chat_id:
        logger.warning("No chat_id provided, skipping notification")
        return False
    import httpx
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info(f"Telegram notification sent to {chat_id}")
                return True
            logger.error("Telegram API error: HTTP %s", resp.status_code)
            return False
        except Exception as e:
            logger.warning("Failed to send Telegram notification attempt %s: %s", attempt, type(e).__name__)
            if attempt < 3:
                await asyncio.sleep(2 * attempt)
    return False
