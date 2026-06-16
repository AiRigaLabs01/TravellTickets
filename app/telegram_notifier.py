import logging
from datetime import datetime
from typing import Any

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def _format_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    if h and m:
        return f"{h}ч {m}м"
    elif h:
        return f"{h}ч"
    return f"{m}м"


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%H:%M")


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    months = ["", "января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]
    return f"{dt.day} {months[dt.month]} {dt.year}"


def _airline_name(code: str) -> str:
    from app.city_codes import AIRLINE_NAMES
    name = AIRLINE_NAMES.get(code.upper(), "")
    if name:
        return f"{name} ({code})"
    return code


def _city_label(iata: str) -> str:
    from app.city_codes import IATA_TO_CITY
    name = IATA_TO_CITY.get(iata.upper(), "")
    if name:
        return f"{name} ({iata})"
    return iata


def build_notification_text(route: Any, flight: dict) -> str:
    dep_dt = flight.get("departure_at")
    arr_dt = flight.get("estimated_arrival_at")
    duration = flight.get("duration", 0) or 0
    arrival_note = ", рассчитано" if flight.get("is_estimated_arrival") else ""
    transfers = flight.get("transfers", 0)
    transfers_str = "нет" if transfers == 0 else str(transfers)

    origin_city = _city_label(route.origin)
    dest_city = _city_label(route.destination)

    lines = [
        "🔥 <b>Найден билет по вашим условиям</b>\n",
        f"{origin_city} → {dest_city}",
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

    if flight.get("gate"):
        lines.append(f"🏪 Продавец: {flight['gate']}")

    aviasales_url = flight.get("aviasales_url", "")
    yandex_url = flight.get("yandex_travel_url", "")

    if aviasales_url or yandex_url:
        lines.append("\n🔗 Открыть и проверить:")
        if aviasales_url:
            lines.append(f"• <a href='{aviasales_url}'>Aviasales</a>")
        if yandex_url:
            lines.append(f"• <a href='{yandex_url}'>Яндекс Путешествия</a>")

    lines.append(
        "\n<i>⚠️ Цены из кэша Aviasales — уточняйте актуальную цену у продавца перед покупкой.</i>"
    )

    return "\n".join(lines)


async def send_telegram_notification(chat_id: str, text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not configured, skipping notification")
        return False
    if not chat_id:
        logger.warning("No chat_id provided, skipping notification")
        return False

    try:
        import httpx
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info(f"Telegram notification sent to {chat_id}")
                return True
            else:
                logger.error(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False
