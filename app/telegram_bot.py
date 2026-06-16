import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup

from app.city_codes import city_label, resolve_iata
from app.config import APP_BASE_URL, TELEGRAM_BOT_TOKEN
from app.database import SessionLocal
from app.date_utils import format_route_date, format_route_date_long, parse_route_date
from app.models import PriceCheck, TrackedRoute
from app.scheduler import check_route, schedule_route

logger = logging.getLogger(__name__)
CREATE_MONITORING_BUTTON = "➕ Создать мониторинг"

bot: Bot | None = None
dp: Dispatcher | None = None


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE_MONITORING_BUTTON), KeyboardButton(text="📋 Мои мониторинги")],
            [KeyboardButton(text="🔎 Проверить сейчас"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def _is_public_app_url() -> bool:
    base = (APP_BASE_URL or "").strip().lower()
    return base.startswith(("http://", "https://")) and not any(host in base for host in ("localhost", "127.0.0.1", "0.0.0.0"))


def route_actions(route_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔎 Проверить сейчас", callback_data=f"check:{route_id}")]]
    if _is_public_app_url():
        rows[0].append(InlineKeyboardButton(text="📈 История", url=f"{APP_BASE_URL}/route/{route_id}"))
        rows.append([InlineKeyboardButton(text="✏️ Изменить", url=f"{APP_BASE_URL}/route/{route_id}/edit"), InlineKeyboardButton(text="⏸ Остановить", callback_data=f"stop:{route_id}")])
    else:
        rows.append([InlineKeyboardButton(text="⏸ Остановить", callback_data=f"stop:{route_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fmt_price(value) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ") + " ₽"


def _resolve_city_input(value: str) -> str | None:
    code = resolve_iata(value or "")
    if len(code) == 3 and code.isalpha():
        return code.upper()
    return None


def _route_card(route: TrackedRoute, last_check: PriceCheck | None = None) -> str:
    filters = []
    if route.direct_only:
        filters.append("только прямые")
    if route.destination_airports:
        filters.append(f"аэропорты: {route.destination_airports}")
    if route.airline_codes:
        filters.append(f"авиакомпании: {route.airline_codes}")
    filter_text = ", ".join(filters) if filters else "без доп. фильтров"
    lines = [
        f"🛫 <b>{city_label(route.origin)} → {city_label(route.destination)}</b>",
        f"📅 {format_route_date_long(route.departure_date)}",
        f"💰 До {_fmt_price(route.max_price)}",
        f"⏱ Проверка: каждые {route.interval_minutes} минут",
        f"🎯 Фильтры: {filter_text}",
    ]
    if last_check:
        dep = last_check.departure_at.strftime("%H:%M") if last_check.departure_at else "—"
        arr = last_check.estimated_arrival_at.strftime("%H:%M") if last_check.estimated_arrival_at else "—"
        lines.extend(["", "<b>Текущая проверка</b>", f"💵 Цена: {_fmt_price(last_check.price)}", f"✈️ Рейс: {last_check.airline or '—'} {last_check.flight_number or ''}".strip(), f"🛬 Аэропорт: {last_check.origin_airport or route.origin} → {last_check.destination_airport or route.destination}", f"🕓 Вылет: {dep}", f"🕕 Прилёт: {arr}, рассчитано", f"🏷 Продавец: {last_check.gate or '—'}"])
    else:
        lines.extend(["", "<b>Текущая проверка</b>", "Пока нет данных. Проверка могла не найти билетов по условиям или API ещё не вернул результат."])
    if not _is_public_app_url():
        lines.extend(["", "ℹ️ Веб-ссылки скрыты: APP_BASE_URL указывает на localhost. Укажите публичный HTTPS URL Replit, чтобы появились кнопки История/Изменить."])
    return "\n".join(lines)


class NewRouteStates(StatesGroup):
    origin = State()
    destination = State()
    departure_date = State()
    max_price = State()
    interval = State()
    direct_only = State()


def create_bot() -> tuple[Bot, Dispatcher]:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    b = Bot(token=TELEGRAM_BOT_TOKEN)
    d = Dispatcher(storage=MemoryStorage())
    _register_handlers(d)
    return b, d


def _register_handlers(dp: Dispatcher):
    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        await message.answer("✈️ <b>TravellTickets</b>\nМониторинг цен на авиабилеты\n\nЯ помогу найти дешёвый билет и пришлю уведомление, когда цена подойдёт под ваши условия.\n\nВыберите действие кнопками ниже.", parse_mode="HTML", reply_markup=main_menu())

    @dp.message(Command("help"))
    @dp.message(F.text == "❓ Помощь")
    async def cmd_help(message: Message):
        await message.answer("📖 <b>Справка</b>\n\n➕ Создать мониторинг — добавить маршрут и условия поиска\n📋 Мои мониторинги — список активных мониторингов\n🔎 Проверить сейчас — проверить все мониторинги вручную\n\nДля расширенных фильтров используйте веб-интерфейс:\n" + APP_BASE_URL, parse_mode="HTML", reply_markup=main_menu())

    @dp.message(Command("new"))
    @dp.message(F.text == CREATE_MONITORING_BUTTON)
    @dp.message(F.text == "➕ Новый мониторинг")
    async def cmd_new(message: Message, state: FSMContext):
        await state.set_state(NewRouteStates.origin)
        await message.answer("Введите город или код аэропорта вылета. Например: <b>Екатеринбург</b>, <b>Екат</b> или <b>SVX</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.origin)
    async def process_origin(message: Message, state: FSMContext):
        code = _resolve_city_input(message.text)
        if not code:
            await message.answer("Не понял город вылета. Введите, например: <b>Екатеринбург</b>, <b>Екат</b> или <b>SVX</b>", parse_mode="HTML")
            return
        await state.update_data(origin=code)
        await state.set_state(NewRouteStates.destination)
        await message.answer(f"Выбрано: <b>{city_label(code)} / {code}</b>\n\nВведите город или код назначения. Например: <b>Москва</b>, <b>Моск</b> или <b>MOW</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.destination)
    async def process_destination(message: Message, state: FSMContext):
        code = _resolve_city_input(message.text)
        if not code:
            await message.answer("Не понял город назначения. Введите, например: <b>Москва</b>, <b>Моск</b> или <b>MOW</b>", parse_mode="HTML")
            return
        await state.update_data(destination=code)
        await state.set_state(NewRouteStates.departure_date)
        await message.answer(f"Выбрано: <b>{city_label(code)} / {code}</b>\n\nВведите дату вылета: <b>21.06.2026</b> или <b>2026-06-21</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.departure_date)
    async def process_departure_date(message: Message, state: FSMContext):
        normalized_date = parse_route_date(message.text)
        if not normalized_date:
            await message.answer("Неверный формат. Введите дату как <b>21.06.2026</b> или <b>2026-06-21</b>:", parse_mode="HTML")
            return
        await state.update_data(departure_date=normalized_date)
        await state.set_state(NewRouteStates.max_price)
        await message.answer(f"Дата: <b>{format_route_date(normalized_date)}</b>\n\nМаксимальная цена (₽), например: <b>5000</b>:", parse_mode="HTML")

    @dp.message(NewRouteStates.max_price)
    async def process_max_price(message: Message, state: FSMContext):
        try:
            price = float(message.text.strip().replace(" ", ""))
        except ValueError:
            await message.answer("Введите число, например: 5000")
            return
        await state.update_data(max_price=price)
        await state.set_state(NewRouteStates.interval)
        await message.answer("Интервал проверки: <b>5</b> или <b>10</b> минут?", parse_mode="HTML")

    @dp.message(NewRouteStates.interval)
    async def process_interval(message: Message, state: FSMContext):
        txt = message.text.strip()
        if txt not in ("5", "10"):
            await message.answer("Введите 5 или 10:")
            return
        await state.update_data(interval_minutes=int(txt))
        await state.set_state(NewRouteStates.direct_only)
        await message.answer("Только прямые рейсы? <b>да</b> / <b>нет</b>", parse_mode="HTML")

    @dp.message(NewRouteStates.direct_only)
    async def process_direct_only(message: Message, state: FSMContext):
        direct = message.text.strip().lower() in ("да", "yes", "y", "д", "1", "true")
        data = await state.get_data()
        await state.clear()
        status_message = await message.answer("⏳ <b>Мониторинг создан. Проверяю текущие цены...</b>", parse_mode="HTML", reply_markup=main_menu())
        db = SessionLocal()
        try:
            route = TrackedRoute(origin=data["origin"], destination=data["destination"], departure_date=data["departure_date"], max_price=data["max_price"], interval_minutes=data["interval_minutes"], direct_only=direct, telegram_chat_id=str(message.chat.id), title=f"{city_label(data['origin'])} → {city_label(data['destination'])} {format_route_date(data['departure_date'])}")
            db.add(route)
            db.commit()
            db.refresh(route)
            route_id = route.id
            schedule_route(route)
        finally:
            db.close()
        try:
            await check_route(route_id)
        except Exception as exc:
            logger.exception("Immediate route check failed")
            db = SessionLocal()
            route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
            db.close()
            await status_message.edit_text("✅ <b>Мониторинг создан</b>\n\n" + _route_card(route) + f"\n\n⚠️ Не удалось сразу проверить цены: {exc}", parse_mode="HTML", reply_markup=route_actions(route_id))
            return
        db = SessionLocal()
        try:
            route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
            last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).first()
            await status_message.edit_text("✅ <b>Мониторинг создан</b>\n\n" + _route_card(route, last), parse_mode="HTML", reply_markup=route_actions(route_id))
        finally:
            db.close()

    @dp.message(Command("list"))
    @dp.message(F.text == "📋 Мои мониторинги")
    @dp.message(F.text == "📋 Мои маршруты")
    async def cmd_list(message: Message):
        db = SessionLocal()
        try:
            routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
            if not routes:
                await message.answer("Нет активных мониторингов. Нажмите «➕ Создать мониторинг».", reply_markup=main_menu())
                return
            await message.answer("📋 <b>Активные мониторинги</b>", parse_mode="HTML", reply_markup=main_menu())
            for route in routes:
                last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route.id).order_by(PriceCheck.checked_at.desc()).first()
                await message.answer(_route_card(route, last), parse_mode="HTML", reply_markup=route_actions(route.id))
        finally:
            db.close()

    @dp.message(Command("stop"))
    async def cmd_stop(message: Message):
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("Использование: /stop &lt;id&gt;\nПример: /stop 1", parse_mode="HTML")
            return
        try:
            route_id = int(parts[1])
        except ValueError:
            await message.answer("ID должен быть числом")
            return
        await _stop_route(message, route_id)

    @dp.message(Command("check"))
    @dp.message(F.text == "🔎 Проверить сейчас")
    async def cmd_check(message: Message):
        db = SessionLocal()
        try:
            routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
            if not routes:
                await message.answer("Нет активных мониторингов", reply_markup=main_menu())
                return
            await message.answer(f"🔍 Проверяю {len(routes)} мониторинг(ов)...")
            for route in routes:
                await check_route(route.id)
            await message.answer("✅ Проверка завершена", reply_markup=main_menu())
        finally:
            db.close()

    @dp.callback_query(F.data.startswith("check:"))
    async def cb_check(callback):
        route_id = int(callback.data.split(":", 1)[1])
        await callback.answer("Проверяю мониторинг...")
        await check_route(route_id)
        db = SessionLocal()
        try:
            route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
            last = db.query(PriceCheck).filter(PriceCheck.tracked_route_id == route_id).order_by(PriceCheck.checked_at.desc()).first()
            if route:
                await callback.message.edit_text(_route_card(route, last), parse_mode="HTML", reply_markup=route_actions(route.id))
        finally:
            db.close()

    @dp.callback_query(F.data.startswith("stop:"))
    async def cb_stop(callback):
        route_id = int(callback.data.split(":", 1)[1])
        await callback.answer("Останавливаю мониторинг...")
        await _stop_route(callback.message, route_id)


async def _stop_route(message: Message, route_id: int):
    db = SessionLocal()
    try:
        route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
        if not route:
            await message.answer(f"Мониторинг #{route_id} не найден")
            return
        route.is_active = False
        db.commit()
        from app.scheduler import unschedule_route
        unschedule_route(route_id)
        await message.answer(f"⏹ Мониторинг #{route_id} остановлен", reply_markup=main_menu())
    finally:
        db.close()
