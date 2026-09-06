# TravellTickets ✈️

Сервис мониторинга цен на авиабилеты по внутренним российским рейсам.

## Что это

- Мониторит цены через **Travelpayouts / Aviasales Data API**
- Проверяет цены каждые 5 или 10 минут
- Отправляет уведомления в **Telegram**
- Предоставляет **веб-интерфейс** для управления маршрутами

**Важно:** Сервис не продаёт и не бронирует билеты. Данные берутся из кэша Aviasales — итоговую цену и наличие билета всегда проверяйте у продавца.

---

## Получение TRAVELPAYOUTS_TOKEN

1. Зарегистрируйтесь на [travelpayouts.com](https://www.travelpayouts.com/)
2. Перейдите в раздел **API** → **Aviasales Data API**
3. Скопируйте ваш API Token

---

## Создание Telegram Bot

1. Напишите [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`, задайте имя и username
3. Скопируйте токен вида `123456:ABC-DEF...`
4. Узнайте свой `chat_id`: напишите боту [@userinfobot](https://t.me/userinfobot)

---

## Конфигурация и безопасная подготовка релиза

Шаблон переменных без секретных значений: [.env.example](.env.example).
Реальные `.env`, SSH-ключи, TLS-ключи и токены не добавляются в Git или Docker context.
Не копируйте production-конфигурацию в тестовое окружение.

Разработка: `codex/*` -> PR в `develop` -> отдельный release-PR в `main`.
CI проверяет PR и push в `develop`/`main`: lint, tests, focused secret scan,
сборку контейнера и HTTP smoke-test. Mypy является блокирующей проверкой;
для APScheduler 3.x без типовых метаданных разрешены только отсутствующие импорты.

Локальные проверки (Python 3.11, Poetry 2.4.1):

```console
poetry check --lock
poetry install --no-root
poetry run flake8 -j 1 app tests scripts/check_secrets.py
poetry run pytest
poetry run python scripts/check_secrets.py --history
docker build -t travelltickets:verify .
```

Тесты отключают загрузку `.env` и очищают ключи интеграций; данные тестов хранятся
в SQLite в памяти. Контейнер устанавливает основные зависимости из `poetry.lock`.
`uv.lock` поддерживается для совместимости; источником release-зависимостей остаётся
`poetry.lock`. `requirements.txt` использует объявления из `pyproject.toml` без копии списка.
CI не публикует образ и не выполняет деплой.

Порядок будущей передачи деплоя, аудит доступов и обязательные проверки:
[docs/PLATFORM_HANDOFF.md](docs/PLATFORM_HANDOFF.md).

## Переменные окружения

| Переменная | Описание |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | API-токен Travelpayouts (обязательно) |
| `TRAVELPAYOUTS_MARKER` | Partner ID Travelpayouts для атрибуции бронирований |
| `TRAVELPAYOUTS_WEBSITE_PROJECT_ID` | ID проекта Travelpayouts для сайта |
| `TRAVELPAYOUTS_TELEGRAM_PROJECT_ID` | ID проекта Travelpayouts для Telegram |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram-бота (для уведомлений) |
| `TELEGRAM_CHAT_ID` | Ваш Telegram chat_id (по умолчанию) |
| `APP_BASE_URL` | Публичный URL приложения (для ссылок в боте) |

---

## Запуск в Replit

Добавьте секреты через вкладку **Secrets** и нажмите **Run**.

---

## Использование

### Веб-интерфейс

Откройте приложение → нажмите **«+ Добавить маршрут»** → заполните форму.

**Пример:** SVX → MOW, 18.06.2026, цена до 5000 ₽, только прямые, аэропорт VKO/SVO, авиакомпания DP/SU.

### Telegram-бот

```
/new    — добавить маршрут
/list   — список маршрутов
/check  — проверить прямо сейчас
/stop 1 — остановить маршрут #1
/help   — справка
```

Для расширенных фильтров используйте веб-интерфейс.

---

## Как работает мониторинг

1. При добавлении маршрута APScheduler создаёт задачу с заданным интервалом
2. Каждые N минут выполняется запрос к Aviasales Data API
3. Ответ фильтруется по всем заданным критериям
4. Если найдена цена ≤ max_price (или ниже предыдущей лучшей) — отправляется Telegram-уведомление
5. Повторное уведомление по одному рейсу с той же ценой не отправляется

---

## Ограничения API

- Travelpayouts Data API возвращает **кэшированные данные** Aviasales — реальная цена может отличаться
- API не возвращает `arrival_at`, поэтому время прилёта **рассчитывается**: `departure_at + duration_minutes`
- Признак `is_estimated_arrival = true` сохраняется в БД, в UI отображается как `~`
- Яндекс Путешествия используется только как дополнительная ссылка для ручной проверки

---

## Коды аэропортов Москвы

| Код | Аэропорт |
|-----|----------|
| MOW | Вся Москва (все аэропорты) |
| SVO | Шереметьево |
| DME | Домодедово |
| VKO | Внуково |

## Популярные авиакомпании

| Код | Авиакомпания |
|-----|-------------|
| SU | Аэрофлот |
| DP | Победа |
| S7 | S7 Airlines |
| U6 | Уральские авиалинии |
| N4 | Nordwind |
| 5N | Smartavia |
