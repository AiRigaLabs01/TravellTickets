import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.config import TELEGRAM_BOT_TOKEN, APP_BASE_URL
from app.database import SessionLocal
from app.models import TrackedRoute
from app.scheduler import check_route, schedule_route

logger = logging.getLogger(__name__)

bot: Bot | None = None
dp: Dispatcher | None = None


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
            "✈️ <b>TravellTickets</b> — мониторинг цен на авиабилеты\n\n"
            "Команды:\n"
            "/new — добавить маршрут для мониторинга\n"
            "/list — список активных маршрутов\n"
            "/check — проверить все маршруты прямо сейчас\n"
            "/stop — остановить маршрут\n"
            "/help — помощь\n\n"
            f"🌐 Веб-интерфейс: {APP_BASE_URL}",
            parse_mode="HTML",
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "📖 <b>Справка</b>\n\n"
            "/new — добавить базовый маршрут через бот\n"
            "/list — все активные маршруты\n"
            "/check — немедленная проверка всех маршрутов\n"
            "/stop &lt;id&gt; — остановить маршрут по ID\n\n"
            "Для расширенных фильтров (аэропорт прилёта, авиакомпания, время вылета/прилёта) "
            "используйте веб-интерфейс:\n"
            f"{APP_BASE_URL}",
            parse_mode="HTML",
        )

    @dp.message(Command("new"))
    async def cmd_new(message: Message, state: FSMContext):
        await state.set_state(NewRouteStates.origin)
        await message.answer(
            "Введите код аэропорта вылета (например: <b>SVX</b>):",
            parse_mode="HTML",
        )

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
                title=f"{data['origin']} → {data['destination']} {data['departure_date']}",
            )
            db.add(route)
            db.commit()
            db.refresh(route)
            schedule_route(route)

            await message.answer(
                f"✅ Маршрут #{route.id} добавлен!\n"
                f"{route.origin} → {route.destination} | {route.departure_date}\n"
                f"Макс. цена: {int(route.max_price):,} ₽\n"
                f"Прямые: {'да' if route.direct_only else 'нет'}\n"
                f"Интервал: {route.interval_minutes} мин\n\n"
                f"Для расширенных фильтров: {APP_BASE_URL}/route/{route.id}/edit",
                parse_mode=None,
            )
        finally:
            db.close()

    @dp.message(Command("list"))
    async def cmd_list(message: Message):
        db = SessionLocal()
        try:
            routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
            if not routes:
                await message.answer("Нет активных маршрутов. Добавьте через /new")
                return
            lines = ["📋 <b>Активные маршруты:</b>\n"]
            for r in routes:
                price_str = f"{int(r.last_best_price):,} ₽" if r.last_best_price else "нет данных"
                lines.append(
                    f"#{r.id} {r.origin}→{r.destination} {r.departure_date} "
                    f"| ≤{int(r.max_price):,}₽ | лучшая: {price_str}"
                )
            await message.answer("\n".join(lines), parse_mode="HTML")
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
            await message.answer(f"⏹ Маршрут #{route_id} остановлен")
        finally:
            db.close()

    @dp.message(Command("check"))
    async def cmd_check(message: Message):
        db = SessionLocal()
        try:
            routes = db.query(TrackedRoute).filter(TrackedRoute.is_active == True).all()
            if not routes:
                await message.answer("Нет активных маршрутов")
                return
            await message.answer(f"🔍 Проверяю {len(routes)} маршрут(ов)...")
            for route in routes:
                await check_route(route.id)
            await message.answer("✅ Проверка завершена")
        finally:
            db.close()
