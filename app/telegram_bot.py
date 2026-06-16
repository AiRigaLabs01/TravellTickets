import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from app.city_codes import city_label
from app.config import TELEGRAM_BOT_TOKEN, APP_BASE_URL
from app.database import SessionLocal
from app.models import PriceCheck, TrackedRoute
from app.scheduler import check_route, schedule_route

logger = logging.getLogger(__name__)

bot: Bot | None = None
dp: Dispatcher | None = None


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новый мониторинг"), KeyboardButton(text="📋 Мои маршруты")],
            [KeyboardButton(text="🔎 Проверить сейчас"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def _fmt_price(value) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ") + " ₽"


def _route_card(route: TrackedRoute, last_check: PriceCheck | None = None) -> str:
    origin = city_label(route.origin)
    destination = city_label(route.destination)
    filters = []
    if route.direct_only:
        filters.append("только прямые")
    if route.destination_airports:
        filters.append(f"аэропорты: {route.destination_airports}")
    if route.airline_codes:
        filters.append(f"авиакомпании: {route.airline_codes}")
    filter_text = ", ".join(filters) if filters else "без доп. фильтров"

    lines = [
        f"🛫 <b>{origin} → {destination}</b>",
        f"📅 {route.departure_date}",
        f"💰 До {_fmt_price(route.max_price)}",
        f"⏱ Проверка: каждые {route.interval_minutes} минут",
        f"🎯 Фильтры: {filter_text}",
    ]

    if last_check:
        dep = last_check.departure_at.strftime("%H:%M") if last_check.departure_at else "—"
        arr = last_check.estimated_arrival_at.strftime("%H:%M") if last_check.estimated_arrival_at else "—"
        lines.extend([
            "",
            "<b>Текущая проверка</b>",
            f"💵 Цена: {_fmt_price(last_check.price)}",
            f"✈️ Рейс: {last_check.airline or '—'} {last_check.flight_number or ''}".strip(),
            f"🛬 Аэропорт: {last_check.origin_airport or route.origin} → {last_check.destination_airport or route.destination}",
            f"🕓 Вылет: {dep}",
            f"🕕 Прилёт: {arr}, рассчитано",
            f"🏷 Продавец: {last_check.gate or '—'}",
        ])
    else:
        lines.extend(["", "<b>Текущая проверка</b>", "Пока нет данных. Проверка могла не найти билетов по условиям или API ещё не вернул результат."])

    lines.append("")
    lines.append(f"Открыть текущие цены: {APP_BASE_URL}/route/{route.id}")
    lines.append(f"Изменить фильтры: {APP_BASE_URL}/route/{route.id}/edit")
    lines.append(f"Остановить: /stop {route.id}")
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
        await message.answer(
            "✈️ <b>TravellTickets</b>\n"
            "Мониторинг цен на авиабилеты\n\n"
            "Я помогу найти дешёвый билет и пришлю уведомление, когда цена подойдёт под ваши условия.\n\n"
            "Выберите действие кнопками ниже.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

    @dp.message(Command("help"))
    @dp.message(F.text == "❓ Помощь")
    async def cmd_help(message: Message):
        await message.answer(
            "📖 <b>Справка</b>\n\n"
            "➕ Новый мониторинг — добавить маршрут\n"
            "📋 Мои маршруты — список активных маршрутов\n"
            "🔎 Проверить сейчас — проверить все маршруты вручную\n\n"
            "Для расширенных фильтров используйте веб-интерфейс:\n"
            f"{APP_BASE_URL}",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

    @dp.message(Command("new"))
    @dp.message(F.text == "➕ Новый мониторинг")
    async def cmd_new(message: Message, state: FSMContext):
        await state.set_state(NewRouteStates.origin)
        await message.answer("Введите код аэропорта вылета (например: <b>SVX</b>):", parse_mode="HTML")

    @dp.message(NewRouteStates.origin)
    async def process_origin(message: Message, state: FSMContext):
        await state.update_data(origin=message.text.strip().upper())
        await state.set_state(NewRouteStates.destination)
        await message.answer("Введите код аэропорта назначения (например: <b>MOW</b>):", parse_mode="HTML")

    @dp.message(NewRouteStates.destination)
    async def process_destination(message: Message, state: FSMContext):
        await state.update_data(destination=message.text.strip().upper())
        await state.set_state(NewRouteStates.departure_date)
        await message.answer("Введите дату вылета в формате <b>ГГГГ-ММ-ДД</b> (например: 2026-06-18):", parse_mode="HTML")

    @dp.message(NewRouteStates.departure_date)
    async def process_departure_date(message: Message, state: FSMContext):
        date_str = message.text.strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            await message.answer("Неверный формат. Введите дату как ГГГГ-ММ-ДД:")
            return
        await state.update_data(departure_date=date_str)
        await state.set_state(NewRouteStates.max_price)
        await message.answer("Максимальная цена (₽), например: <b>5000</b>:", parse_mode="HTML")

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
        txt = message.text.strip().lower()
        direct = txt in ("да", "yes", "y", "д", "1", "true")
        data = await state.get_data()
        await state.clear()

        status_message = await message.answer(
            "⏳ <b>Мониторинг создан. Проверяю текущие цены...</b>",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

        db = SessionLocal()
        try:
            route = TrackedRoute(
                origin=data["origin"],
                destination=data["destination"],
                departure_date=data["departure_date"],
                max_price=data["max_price"],
                interval_minutes=data["interval_minutes"],
                direct_only=direct,
                telegram_chat_id=str(message.chat.id),
                title=f"{city_label(data['origin'])} → {city_label(data['destination'])} {data['departure_date']}",
            )
            db.add(route)
            db.commit()
            db.refresh(route)
            schedule_route(route)
        finally:
            db.close()

        try:
            await check_route(route.id)
        except Exception as exc:
            logger.exception("Immediate route check failed")
            await status_message.edit_text(
                "✅ <b>Мониторинг создан</b>\n\n"
                + _route_card(route)
                + f"\n\n⚠️ Не удалось сразу проверить цены: {exc}",
                parse_mode="HTML",
            )
            return

        db = SessionLocal()
        try:
            route = db.query(TrackedRoute).filter(TrackedRoute.id == route.id).first()
            last = (
                db.query(PriceCheck)
                .filter(PriceCheck.tracked_route_id == route.id)
                .order_by(PriceCheck.checked_at.desc())
                .first()
            )
            await status_message.edit_text(
                "✅ <b>Мониторинг создан</b>\n\n" + _route_card(route, last),
                parse_mode="HTML",
            )
        finally:
            db.close()

    @dp.message(Command("list"))
    @dp.message(F.text == "📋 Мои маршруты")
    async def cmd_list(message: Message):
        db = SessionLocal()
        try:
            routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
            if not routes:
                await message.answer("Нет активных маршрутов. Добавьте через /new", reply_markup=main_menu())
                return
            await message.answer("📋 <b>Активные маршруты</b>", parse_mode="HTML", reply_markup=main_menu())
            for route in routes:
                last = (
                    db.query(PriceCheck)
                    .filter(PriceCheck.tracked_route_id == route.id)
                    .order_by(PriceCheck.checked_at.desc())
                    .first()
                )
                await message.answer(_route_card(route, last), parse_mode="HTML")
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

        db = SessionLocal()
        try:
            route = db.query(TrackedRoute).filter(TrackedRoute.id == route_id).first()
            if not route:
                await message.answer(f"Маршрут #{route_id} не найден")
                return
            route.is_active = False
            db.commit()
            from app.scheduler import unschedule_route
            unschedule_route(route_id)
            await message.answer(f"⏹ Маршрут #{route_id} остановлен", reply_markup=main_menu())
        finally:
            db.close()

    @dp.message(Command("check"))
    @dp.message(F.text == "🔎 Проверить сейчас")
    async def cmd_check(message: Message):
        db = SessionLocal()
        try:
            routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
            if not routes:
                await message.answer("Нет активных маршрутов", reply_markup=main_menu())
                return
            await message.answer(f"🔍 Проверяю {len(routes)} маршрут(ов)...")
            for route in routes:
                await check_route(route.id)
            await message.answer("✅ Проверка завершена", reply_markup=main_menu())
        finally:
            db.close()
