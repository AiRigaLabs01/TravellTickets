import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy import or_

from app.city_codes import city_label, resolve_iata
from app.config import APP_BASE_URL, TELEGRAM_BOT_TOKEN
from app.database import SessionLocal
from app.date_utils import format_msk_time, format_route_date, format_route_date_long, parse_route_date
from app.auth import create_telegram_access_token, normalize_telegram_username
from app.models import Notification, PriceCheck, TrackedRoute
from app.scheduler import check_route, schedule_route, unschedule_route
from app.services.locations import location_choices as service_location_choices
from app.services.locations import resolve_location_code, resolve_route_location, should_offer_location_choices as service_should_offer_location_choices
from app.services.routes import delete_route as delete_route_service
from app.yandex_links import build_yandex_travel_url_for_route

logger = logging.getLogger(__name__)
CREATE_MONITORING_BUTTON = "➕ Создать мониторинг"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE_MONITORING_BUTTON), KeyboardButton(text="📋 Мои мониторинги")],
            [KeyboardButton(text="🔎 Проверить сейчас"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in r] for r in rows], resize_keyboard=True, one_time_keyboard=True)


def chat_id(message: Message) -> str:
    return str(message.chat.id)


def creator_name(message: Message) -> str:
    u = message.from_user
    if not u:
        return f"Telegram chat {message.chat.id}"
    if u.username:
        return f"@{u.username}"
    return " ".join(p for p in [u.first_name, u.last_name] if p) or str(u.id)


def creator_username(message: Message) -> str | None:
    u = message.from_user
    return u.username if u and u.username else None


def creator_user_id(message: Message) -> str | None:
    return str(message.from_user.id) if message.from_user else None


def public_app_url() -> bool:
    base = (APP_BASE_URL or "").strip().lower()
    return base.startswith(("http://", "https://")) and not any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0"))


def owned_routes(db, message: Message):
    username = normalize_telegram_username(creator_username(message))
    filters = [TrackedRoute.telegram_chat_id == chat_id(message)]
    if username:
        filters.extend([TrackedRoute.creator_username == username, TrackedRoute.notification_username == username])
    return db.query(TrackedRoute).filter(TrackedRoute.is_active == True, or_(*filters))


def owned_route(db, message: Message, route_id: int):
    username = normalize_telegram_username(creator_username(message))
    filters = [TrackedRoute.telegram_chat_id == chat_id(message)]
    if username:
        filters.extend([TrackedRoute.creator_username == username, TrackedRoute.notification_username == username])
    return db.query(TrackedRoute).filter(TrackedRoute.id == route_id, or_(*filters)).first()


def route_web_url(route: TrackedRoute, message: Message | None = None) -> str:
    link_chat_id = chat_id(message) if message else route.telegram_chat_id
    link_username = creator_username(message) if message else route.creator_username
    token = create_telegram_access_token(link_chat_id, link_username, route.id)
    return f"{APP_BASE_URL}/tg/route/{route.id}?token={token}"


def monitorings_web_url(message: Message) -> str:
    token = create_telegram_access_token(chat_id(message), creator_username(message))
    return f"{APP_BASE_URL}/tg/monitorings?token={token}"


def route_actions(route: TrackedRoute, message: Message | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔎 Проверить сейчас", callback_data=f"check:{route.id}"), InlineKeyboardButton(text="🔗 Яндекс", url=build_yandex_travel_url_for_route(route))]]
    if public_app_url():
        rows.append([InlineKeyboardButton(text="📈 История", url=route_web_url(route, message))])
    rows.append([InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{route.id}"), InlineKeyboardButton(text="⏸ Остановить", callback_data=f"stop:{route.id}")])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{route.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_menu(route_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛫 Откуда", callback_data=f"edit_origin:{route_id}"), InlineKeyboardButton(text="🛬 Куда", callback_data=f"edit_destination:{route_id}")],
        [InlineKeyboardButton(text="💰 Цена", callback_data=f"edit_price:{route_id}"), InlineKeyboardButton(text="📅 Дата", callback_data=f"edit_date:{route_id}")],
        [InlineKeyboardButton(text="👥 Пассажиры", callback_data=f"edit_passengers:{route_id}"), InlineKeyboardButton(text="🧳 Багаж", callback_data=f"edit_baggage:{route_id}")],
        [InlineKeyboardButton(text="⏱ Интервал", callback_data=f"edit_interval:{route_id}"), InlineKeyboardButton(text="🎯 Прямые", callback_data=f"edit_direct:{route_id}")],
    ])


def fmt_price(v) -> str:
    return "нет данных" if v is None else f"{int(v):,}".replace(",", " ") + " ₽"


def resolve_city(text: str) -> str | None:
    code = resolve_iata(text or "")
    return code.upper() if len(code) == 3 and code.isalpha() else None


def location_choices(text: str) -> list[tuple[str, str]]:
    return service_location_choices(text, limit=6)


def location_keyboard(text: str) -> ReplyKeyboardMarkup | None:
    choices = location_choices(text)
    if not choices:
        return None
    return kb([[label] for label, _ in choices])


def resolve_location(text: str) -> str | None:
    return resolve_location_code(text)


def resolve_route_choice(text: str):
    return resolve_route_location(text)


def should_offer_location_choices(text: str) -> bool:
    return service_should_offer_location_choices(text)


def parse_interval(text: str | None) -> int | None:
    try:
        value = int((text or "").strip())
    except ValueError:
        return None
    if value < 5 or value > 15:
        return None
    return value


def parse_passengers(text: str) -> tuple[int, int, int] | None:
    t = (text or "").strip().lower()
    presets = {
        "1 взрослый": (1, 0, 0), "2 взрослых": (2, 0, 0),
        "1 взрослый + 1 ребёнок": (1, 1, 0), "1 взрослый + 1 ребенок": (1, 1, 0),
        "2 взрослых + 1 ребёнок": (2, 1, 0), "2 взрослых + 1 ребенок": (2, 1, 0),
    }
    if t in presets:
        return presets[t]
    parts = t.replace(" ", "").replace(";", ",").replace("/", ",").split(",")
    if len(parts) != 3:
        return None
    try:
        a, c, i = [int(x) for x in parts]
    except ValueError:
        return None
    if a < 1 or a > 9 or c < 0 or i < 0 or a + c + i > 9:
        return None
    return a, c, i


def passengers_text(route: TrackedRoute) -> str:
    parts = [f"{route.adult_seats or 1} взр."]
    if route.children_seats:
        parts.append(f"{route.children_seats} дет.")
    if route.infant_seats:
        parts.append(f"{route.infant_seats} млад.")
    return ", ".join(parts)


def route_card(route: TrackedRoute, last: PriceCheck | None = None) -> str:
    filters = []
    if route.direct_only:
        filters.append("только прямые")
    if route.destination_airports:
        filters.append(f"аэропорты: {route.destination_airports}")
    if route.origin_airports:
        filters.append(f"аэропорты вылета: {route.origin_airports}")
    if route.airline_codes:
        filters.append(f"авиакомпании: {route.airline_codes}")
    if route.baggage_required:
        filters.append("нужен багаж")
    trip = "туда-обратно" if route.trip_type == "roundtrip" else "только туда"
    if route.return_date:
        trip += f", обратно {format_route_date_long(route.return_date)}"
    lines = [
        f"🛫 <b>{city_label(route.origin)} → {city_label(route.destination)}</b>",
        f"📅 {format_route_date_long(route.departure_date)}",
        f"🔁 Тип: {trip}",
        f"👥 Пассажиры: {passengers_text(route)}",
        f"🧳 Багаж: {'нужен' if route.baggage_required else 'не нужен'}",
        f"💰 До {fmt_price(route.max_price)}",
        f"👤 Автор: {route.creator_display_name or route.telegram_chat_id or 'Telegram'}",
        f"⏱ Проверка: каждые {route.interval_minutes} минут",
        f"🎯 Фильтры: {', '.join(filters) if filters else 'без доп. фильтров'}",
    ]
    if last:
        matches = getattr(last, "matches_filters", True)
        if matches:
            lines += ["", "<b>Текущая проверка</b>", f"💵 Цена: {fmt_price(last.price)}"]
        else:
            diff = int(last.price - route.max_price)
            lines += ["", "<b>Минимальная найденная цена выше вашего лимита</b>", f"💵 Найдено: {fmt_price(last.price)}", f"🎯 Ваш лимит: {fmt_price(route.max_price)}"]
            if diff > 0:
                lines.append(f"↗️ Выше лимита на {fmt_price(diff)}")
        lines += [
            f"✈️ Рейс: {last.airline or '—'} {last.flight_number or ''}".strip(),
            f"🛬 Аэропорт: {last.origin_airport or route.origin} → {last.destination_airport or route.destination}",
            f"🕓 Вылет: {format_msk_time(last.departure_at)}",
            f"🕕 Прилёт: {format_msk_time(last.estimated_arrival_at)}, рассчитано",
            f"🏷 Продавец: {last.gate or '—'}",
        ]
    else:
        lines += ["", "<b>Текущая проверка</b>", "Пока нет данных. Проверка могла не найти билетов по условиям или API ещё не вернул результат."]
    return "\n".join(lines)


async def send_route(message: Message, route_id: int, prefix: str = "📊 <b>Результат ручной проверки</b>"):
    db = SessionLocal()
    try:
        r = owned_route(db, message, route_id)
        if not r:
            return
        last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).first()
        await message.answer(f"{prefix}\n\n" + route_card(r, last), parse_mode="HTML", reply_markup=route_actions(r, message))
    finally:
        db.close()


async def check_and_send_route(message: Message, route_id: int, prefix: str | None = None) -> None:
    try:
        await check_route(route_id)
        await send_route(message, route_id, prefix or "Результат ручной проверки")
    except Exception:
        logger.exception("Manual route check failed")
        await message.answer("Не удалось проверить цены. Попробуйте ещё раз.", reply_markup=main_menu())


def reset_results(db, route: TrackedRoute):
    db.query(Notification).filter(Notification.tracked_route_id == route.id).delete()
    db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route.id).delete()
    route.last_best_price = None
    route.last_checked_at = None
    route.last_error = None
    route.no_change_checks_count = 0


async def update_route(message: Message, route_id: int, reset: bool = False, **fields):
    db = SessionLocal()
    try:
        r = owned_route(db, message, route_id)
        if not r:
            await message.answer(f"Мониторинг #{route_id} не найден среди ваших мониторингов")
            return
        for k, v in fields.items():
            setattr(r, k, v)
        r.title = f"{city_label(r.origin)} → {city_label(r.destination)} {format_route_date(r.departure_date)}"
        r.last_error = None
        if reset:
            reset_results(db, r)
        db.commit()
        db.refresh(r)
        schedule_route(r)
        await send_route(message, route_id, "✅ <b>Мониторинг обновлён</b>")
    finally:
        db.close()


class NewRouteStates(StatesGroup):
    origin = State(); destination = State(); trip_type = State(); departure_date = State(); return_date = State(); passengers = State(); baggage = State(); max_price = State(); interval = State(); direct_only = State()


class EditRouteStates(StatesGroup):
    origin = State(); destination = State(); price = State(); date = State(); passengers = State(); interval = State()


def create_bot() -> tuple[Bot, Dispatcher]:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    b = Bot(token=TELEGRAM_BOT_TOKEN, session=AiohttpSession(timeout=60))
    d = Dispatcher(storage=MemoryStorage())
    register_handlers(d)
    return b, d


def register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def start(message: Message):
        await message.answer("✈️ <b>TravellTickets</b>\nМониторинг цен на авиабилеты\n\nВыберите действие кнопками ниже.", parse_mode="HTML", reply_markup=main_menu())

    @dp.message(Command("help"))
    @dp.message(F.text == "❓ Помощь")
    async def help_msg(message: Message):
        await message.answer("📖 <b>Справка</b>\n\n➕ Создать мониторинг — добавить маршрут и условия поиска\n📋 Мои мониторинги — список только ваших активных мониторингов\n🔎 Проверить сейчас — проверить только ваши мониторинги вручную", parse_mode="HTML", reply_markup=main_menu())

    @dp.message(Command("new"))
    @dp.message(F.text == CREATE_MONITORING_BUTTON)
    @dp.message(F.text == "➕ Новый мониторинг")
    async def new_route(message: Message, state: FSMContext):
        await state.set_state(NewRouteStates.origin)
        await message.answer("Введите город или код аэропорта вылета. Например: <b>Екатеринбург</b>, <b>Екат</b> или <b>SVX</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.origin)
    async def new_origin(message: Message, state: FSMContext):
        if should_offer_location_choices(message.text):
            await message.answer("Выберите город или конкретный аэропорт из справочника:", reply_markup=location_keyboard(message.text))
            return
        selected = resolve_route_choice(message.text)
        if not selected:
            await message.answer("Не понял город вылета. Выберите вариант из справочника или введите IATA-код.", parse_mode="HTML", reply_markup=location_keyboard(message.text))
            return
        await state.update_data(origin=selected.code, origin_airports=selected.airport_code)
        await state.set_state(NewRouteStates.destination)
        await message.answer(f"Выбрано: <b>{city_label(selected.code)} / {selected.code}</b>\n\nВведите город или код назначения. Например: <b>Москва</b>, <b>Моск</b> или <b>MOW</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.destination)
    async def new_destination(message: Message, state: FSMContext):
        if should_offer_location_choices(message.text):
            await message.answer("Выберите город или конкретный аэропорт из справочника:", reply_markup=location_keyboard(message.text))
            return
        selected = resolve_route_choice(message.text)
        if not selected:
            await message.answer("Не понял город назначения. Выберите вариант из справочника или введите IATA-код.", parse_mode="HTML", reply_markup=location_keyboard(message.text))
            return
        await state.update_data(destination=selected.code, destination_airports=selected.airport_code)
        await state.set_state(NewRouteStates.trip_type)
        await message.answer(f"Выбрано: <b>{city_label(selected.code)} / {selected.code}</b>\n\nВыберите тип перелёта:", parse_mode="HTML", reply_markup=kb([["Только туда", "Туда-обратно"]]))

    @dp.message(NewRouteStates.trip_type)
    async def new_trip_type(message: Message, state: FSMContext):
        await state.update_data(trip_type="roundtrip" if (message.text or "").lower().strip() == "туда-обратно" else "oneway")
        await state.set_state(NewRouteStates.departure_date)
        await message.answer("Введите дату вылета туда: <b>21.06.2026</b> или <b>2026-06-21</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.departure_date)
    async def new_date(message: Message, state: FSMContext):
        d = parse_route_date(message.text)
        if not d:
            await message.answer("Неверный формат. Введите дату как <b>21.06.2026</b> или <b>2026-06-21</b>:", parse_mode="HTML")
            return
        await state.update_data(departure_date=d)
        data = await state.get_data()
        if data.get("trip_type") == "roundtrip":
            await state.set_state(NewRouteStates.return_date)
            await message.answer("Введите дату обратного вылета: <b>28.06.2026</b> или <b>2026-06-28</b>", parse_mode="HTML")
        else:
            await state.update_data(return_date=None)
            await state.set_state(NewRouteStates.passengers)
            await message.answer("Выберите пассажиров или введите вручную: <b>2,1,0</b>", parse_mode="HTML", reply_markup=kb([["1 взрослый", "2 взрослых"], ["1 взрослый + 1 ребёнок", "2 взрослых + 1 ребёнок"]]))

    @dp.message(NewRouteStates.return_date)
    async def new_return_date(message: Message, state: FSMContext):
        d = parse_route_date(message.text)
        if not d:
            await message.answer("Неверный формат. Введите дату обратно как <b>28.06.2026</b> или <b>2026-06-28</b>:", parse_mode="HTML")
            return
        await state.update_data(return_date=d)
        await state.set_state(NewRouteStates.passengers)
        await message.answer("Выберите пассажиров или введите вручную: <b>2,1,0</b>", parse_mode="HTML", reply_markup=kb([["1 взрослый", "2 взрослых"], ["1 взрослый + 1 ребёнок", "2 взрослых + 1 ребёнок"]]))

    @dp.message(NewRouteStates.passengers)
    async def new_passengers(message: Message, state: FSMContext):
        p = parse_passengers(message.text)
        if not p:
            await message.answer("Не понял количество пассажиров. Введите так: <b>2,1,0</b>", parse_mode="HTML")
            return
        await state.update_data(adult_seats=p[0], children_seats=p[1], infant_seats=p[2])
        await state.set_state(NewRouteStates.baggage)
        await message.answer("Нужен багаж?", reply_markup=kb([["Без багажа", "Нужен багаж"]]))

    @dp.message(NewRouteStates.baggage)
    async def new_baggage(message: Message, state: FSMContext):
        await state.update_data(baggage_required=(message.text or "").lower().strip() in ("нужен багаж", "багаж", "да", "yes", "1", "true"))
        await state.set_state(NewRouteStates.max_price)
        await message.answer("Максимальная цена (₽), например: <b>5000</b>:", parse_mode="HTML")

    @dp.message(NewRouteStates.max_price)
    async def new_price(message: Message, state: FSMContext):
        try:
            price = float(message.text.strip().replace(" ", ""))
        except ValueError:
            await message.answer("Введите число, например: 5000")
            return
        await state.update_data(max_price=price)
        await state.set_state(NewRouteStates.interval)
        await message.answer("Введите интервал проверки в минутах от <b>5</b> до <b>15</b>. Можно указать любое число в этом диапазоне.", parse_mode="HTML")

    @dp.message(NewRouteStates.interval)
    async def new_interval(message: Message, state: FSMContext):
        interval = parse_interval(message.text)
        if interval is None:
            await message.answer("Введите число минут от <b>5</b> до <b>15</b>. Например: <b>10</b>", parse_mode="HTML")
            return
        await state.update_data(interval_minutes=interval)
        await state.set_state(NewRouteStates.direct_only)
        await message.answer("Только прямые рейсы?", reply_markup=kb([["Да", "Нет"]]))

    @dp.message(NewRouteStates.direct_only)
    async def new_direct(message: Message, state: FSMContext):
        direct = message.text.strip().lower() in ("да", "yes", "y", "д", "1", "true")
        data = await state.get_data()
        await state.clear()
        await message.answer("⏳ <b>Мониторинг создан. Проверяю текущие цены...</b>", parse_mode="HTML", reply_markup=main_menu())
        db = SessionLocal()
        try:
            r = TrackedRoute(origin=data["origin"], destination=data["destination"], origin_airports=data.get("origin_airports"), destination_airports=data.get("destination_airports"), departure_date=data["departure_date"], return_date=data.get("return_date"), trip_type=data.get("trip_type", "oneway"), adult_seats=data.get("adult_seats", 1), children_seats=data.get("children_seats", 0), infant_seats=data.get("infant_seats", 0), baggage_required=data.get("baggage_required", False), max_price=data["max_price"], interval_minutes=data["interval_minutes"], direct_only=direct, telegram_chat_id=chat_id(message), creator_source="telegram", creator_display_name=creator_name(message), creator_username=creator_username(message), creator_telegram_user_id=creator_user_id(message), title=f"{city_label(data['origin'])} → {city_label(data['destination'])} {format_route_date(data['departure_date'])}")
            db.add(r); db.commit(); db.refresh(r); route_id = r.id; schedule_route(r)
        finally:
            db.close()
        asyncio.create_task(check_and_send_route(message, route_id, "✅ <b>Мониторинг создан</b>"))

    @dp.message(Command("list"))
    @dp.message(F.text == "📋 Мои мониторинги")
    @dp.message(F.text == "📋 Мои маршруты")
    async def list_routes(message: Message):
        db = SessionLocal()
        try:
            routes = owned_routes(db, message).all()
            if not routes:
                await message.answer("Нет активных мониторингов. Нажмите «➕ Создать мониторинг».", reply_markup=main_menu())
                return
            web_markup = None
            if public_app_url():
                web_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Открыть в вебе", url=monitorings_web_url(message))]])
            await message.answer("📋 <b>Ваши активные мониторинги</b>", parse_mode="HTML", reply_markup=web_markup or main_menu())
            for r in routes:
                last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == r.id).order_by(PriceCheck.checked_at.desc()).first()
                await message.answer(route_card(r, last), parse_mode="HTML", reply_markup=route_actions(r, message))
        finally:
            db.close()

    @dp.callback_query(F.data.startswith("edit:"))
    async def edit(callback):
        route_id = int(callback.data.split(":", 1)[1])
        await callback.answer("Что изменить?")
        await callback.message.answer("✏️ Что изменить в мониторинге?", reply_markup=edit_menu(route_id))

    async def ask_edit(callback, state, route_id: int, st, text: str):
        await state.update_data(edit_route_id=route_id); await state.set_state(st); await callback.answer(); await callback.message.answer(text, parse_mode="HTML")

    @dp.callback_query(F.data.startswith("edit_origin:"))
    async def cb_edit_origin(callback, state: FSMContext):
        await ask_edit(callback, state, int(callback.data.split(":", 1)[1]), EditRouteStates.origin, "Введите новый город/аэропорт вылета. Например: <b>Екатеринбург</b>, <b>Екат</b> или <b>SVX</b>")

    @dp.message(EditRouteStates.origin)
    async def edit_origin(message: Message, state: FSMContext):
        if should_offer_location_choices(message.text):
            await message.answer("Выберите город или конкретный аэропорт из справочника:", reply_markup=location_keyboard(message.text))
            return
        selected = resolve_route_choice(message.text)
        if not selected:
            await message.answer("Не понял город вылета. Выберите вариант из справочника или введите IATA-код.", reply_markup=location_keyboard(message.text))
            return
        data = await state.get_data(); await state.clear(); await update_route(message, data["edit_route_id"], reset=True, origin=selected.code, origin_airports=selected.airport_code)

    @dp.callback_query(F.data.startswith("edit_destination:"))
    async def cb_edit_destination(callback, state: FSMContext):
        await ask_edit(callback, state, int(callback.data.split(":", 1)[1]), EditRouteStates.destination, "Введите новый город/аэропорт назначения. Например: <b>Москва</b>, <b>Моск</b> или <b>MOW</b>")

    @dp.message(EditRouteStates.destination)
    async def edit_destination(message: Message, state: FSMContext):
        if should_offer_location_choices(message.text):
            await message.answer("Выберите город или конкретный аэропорт из справочника:", reply_markup=location_keyboard(message.text))
            return
        selected = resolve_route_choice(message.text)
        if not selected:
            await message.answer("Не понял город назначения. Выберите вариант из справочника или введите IATA-код.", reply_markup=location_keyboard(message.text))
            return
        data = await state.get_data(); await state.clear(); await update_route(message, data["edit_route_id"], reset=True, destination=selected.code, destination_airports=selected.airport_code)

    @dp.callback_query(F.data.startswith("edit_price:"))
    async def cb_edit_price(callback, state: FSMContext):
        await ask_edit(callback, state, int(callback.data.split(":", 1)[1]), EditRouteStates.price, "Введите новую максимальную цену, например: <b>5000</b>")

    @dp.message(EditRouteStates.price)
    async def edit_price(message: Message, state: FSMContext):
        try:
            price = float(message.text.strip().replace(" ", ""))
        except ValueError:
            await message.answer("Введите число, например: 5000")
            return
        data = await state.get_data(); await state.clear(); await update_route(message, data["edit_route_id"], max_price=price)

    @dp.callback_query(F.data.startswith("edit_date:"))
    async def cb_edit_date(callback, state: FSMContext):
        await ask_edit(callback, state, int(callback.data.split(":", 1)[1]), EditRouteStates.date, "Введите новую дату вылета: <b>21.06.2026</b> или <b>2026-06-21</b>")

    @dp.message(EditRouteStates.date)
    async def edit_date(message: Message, state: FSMContext):
        d = parse_route_date(message.text)
        if not d:
            await message.answer("Неверный формат даты.")
            return
        data = await state.get_data(); await state.clear(); await update_route(message, data["edit_route_id"], reset=True, departure_date=d)

    @dp.callback_query(F.data.startswith("edit_passengers:"))
    async def cb_edit_passengers(callback, state: FSMContext):
        await ask_edit(callback, state, int(callback.data.split(":", 1)[1]), EditRouteStates.passengers, "Введите пассажиров в формате <b>взрослые,дети,младенцы</b>, например <b>2,1,0</b>")

    @dp.message(EditRouteStates.passengers)
    async def edit_passengers(message: Message, state: FSMContext):
        p = parse_passengers(message.text)
        if not p:
            await message.answer("Не понял количество пассажиров. Введите так: <b>2,1,0</b>", parse_mode="HTML")
            return
        data = await state.get_data(); await state.clear(); await update_route(message, data["edit_route_id"], adult_seats=p[0], children_seats=p[1], infant_seats=p[2])

    @dp.callback_query(F.data.startswith("edit_baggage:"))
    async def cb_edit_baggage(callback):
        rid = int(callback.data.split(":", 1)[1]); await callback.answer(); await callback.message.answer("Выберите багаж:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Без багажа", callback_data=f"set_baggage:0:{rid}"), InlineKeyboardButton(text="Нужен багаж", callback_data=f"set_baggage:1:{rid}")]]))

    @dp.callback_query(F.data.startswith("set_baggage:"))
    async def set_baggage(callback):
        _, value, rid = callback.data.split(":", 2); await callback.answer("Сохраняю..."); await update_route(callback.message, int(rid), baggage_required=(value == "1"))

    @dp.callback_query(F.data.startswith("edit_interval:"))
    async def cb_edit_interval(callback, state: FSMContext):
        await ask_edit(callback, state, int(callback.data.split(":", 1)[1]), EditRouteStates.interval, "Введите новый интервал проверки в минутах от <b>5</b> до <b>15</b>. Можно указать любое число в этом диапазоне.")

    @dp.message(EditRouteStates.interval)
    async def edit_interval(message: Message, state: FSMContext):
        interval = parse_interval(message.text)
        if interval is None:
            await message.answer("Введите число минут от <b>5</b> до <b>15</b>. Например: <b>10</b>", parse_mode="HTML")
            return
        data = await state.get_data(); await state.clear(); await update_route(message, data["edit_route_id"], interval_minutes=interval)

    @dp.callback_query(F.data.startswith("edit_direct:"))
    async def cb_edit_direct(callback):
        rid = int(callback.data.split(":", 1)[1]); await callback.answer(); await callback.message.answer("Только прямые рейсы?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Да", callback_data=f"set_direct:1:{rid}"), InlineKeyboardButton(text="Нет", callback_data=f"set_direct:0:{rid}")]]))

    @dp.callback_query(F.data.startswith("set_direct:"))
    async def set_direct(callback):
        _, value, rid = callback.data.split(":", 2); await callback.answer("Сохраняю..."); await update_route(callback.message, int(rid), direct_only=(value == "1"))

    @dp.message(Command("check"))
    @dp.message(F.text == "🔎 Проверить сейчас")
    async def manual_check(message: Message):
        db = SessionLocal()
        try:
            route_ids = [r.id for r in owned_routes(db, message).all()]
        finally:
            db.close()
        if not route_ids:
            await message.answer("Нет активных мониторингов", reply_markup=main_menu())
            return
        await message.answer(f"🔍 Проверка {len(route_ids)} мониторинг(ов) запущена. Пришлю результаты отдельными сообщениями.")
        for rid in route_ids:
            asyncio.create_task(check_and_send_route(message, rid))

    @dp.callback_query(F.data.startswith("check:"))
    async def cb_check(callback):
        rid = int(callback.data.split(":", 1)[1]); await callback.answer("Проверка запущена"); asyncio.create_task(check_and_send_route(callback.message, rid))

    @dp.callback_query(F.data.startswith("stop:"))
    async def cb_stop(callback):
        rid = int(callback.data.split(":", 1)[1]); await callback.answer("Останавливаю мониторинг..."); await stop_route(callback.message, rid)

    @dp.callback_query(F.data.startswith("delete:"))
    async def cb_delete(callback):
        rid = int(callback.data.split(":", 1)[1]); await callback.answer("Удаляю мониторинг..."); await delete_route(callback.message, rid)

    @dp.message(Command("stop"))
    async def cmd_stop(message: Message):
        p = message.text.split(); await stop_route(message, int(p[1])) if len(p) > 1 else await message.answer("Использование: /stop <id>")

    @dp.message(Command("delete"))
    async def cmd_delete(message: Message):
        p = message.text.split(); await delete_route(message, int(p[1])) if len(p) > 1 else await message.answer("Использование: /delete <id>")


async def stop_route(message: Message, route_id: int):
    db = SessionLocal()
    try:
        r = owned_route(db, message, route_id)
        if not r:
            await message.answer(f"Мониторинг #{route_id} не найден среди ваших мониторингов")
            return
        r.is_active = False; db.commit(); unschedule_route(route_id)
        await message.answer(f"⏹ Мониторинг #{route_id} остановлен", reply_markup=main_menu())
    finally:
        db.close()


async def delete_route(message: Message, route_id: int):
    db = SessionLocal()
    try:
        r = owned_route(db, message, route_id)
        if not r:
            await message.answer(f"Мониторинг #{route_id} не найден среди ваших мониторингов")
            return
        delete_route_service(db, r)
        await message.answer(f"🗑 Мониторинг #{route_id} удалён", reply_markup=main_menu())
    finally:
        db.close()
