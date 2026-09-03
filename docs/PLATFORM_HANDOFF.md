# TravellTickets: подготовка передачи управления деплоем

## Статус и границы

Подготовлено 2026-09-03. Этот PR не переносит сервис, не меняет DNS/production,
не отзывает ключи и не удаляет старое развертывание.

- Последний проверенный production-релиз: `c786320` (проверка 2026-09-02).
- Существующий стек: `/opt/travelltickets`, сайт `https://www.travelltickets.ru`.
- Приложение, PostgreSQL 16 и HAProxy сейчас находятся в legacy Compose-стеке.
- Цель: продукт публикует образ; `AI_Service_Platform` владеет placement,
  runtime-конфигурацией, rollout, rollback, мониторингом и резервными копиями.
- `vps2` является только плановым application-target. Реальный target выбирается
  из `operator/state.csv` и operator config платформы, не из номера VPS.
- По политике платформы PostgreSQL размещается в database pool; приложение
  обращается к нему через управляемый `platform_router` endpoint.

В локальном `AI_Service_Platform` уже есть незакоммиченные изменения `services.yml`
в ветке `codex/travelltickets-travelpayouts`. Не перезаписывать их. Согласовать
отдельный platform-PR с владельцем этих изменений.

## Контракт приложения

| Область | Требование |
| --- | --- |
| Runtime | Python 3.11, Uvicorn, внутренний TCP 5000 |
| Процессы | Один web process одновременно запускает APScheduler и Telegram long polling |
| Масштабирование | Одна активная replica/worker, пока scheduler и polling не вынесены отдельно |
| Health | `GET /healthz`: 200 и `status=ok`; `/health/` дополнительно проверяет БД и показывает состояние auth |
| БД | PostgreSQL 16; уникальная роль/БД и доступ только через разрешённый endpoint |
| Данные | Пользователи, маршруты, найденные цены и уведомления в PostgreSQL |
| Ingress | HTTPS через управляемый edge; backend 5000 не публиковать в Интернет |
| Egress | DNS, HTTPS `api.travelpayouts.com:443`, `api.telegram.org:443`, подключение к БД |
| Artifact | `ghcr.io/airigalabs01/travelltickets@sha256:<digest>` после публикации проверенного релиза |

В текущем черновике platform registry указан только Travelpayouts egress:
добавить Telegram и управляемые DNS/DB-доступы до включения default-deny.
Не переносить legacy `extra_hosts` с фиксированным IP Telegram без проверки.

`init_db()` создаёт таблицы и добавляет отсутствующие колонки при старте.
Флаг `migrations.required=false` из affiliate-handoff не означает отсутствие
изменений схемы во всех релизах: проверить restore и первый старт на копии БД.
В этом PR удалена старая автоматическая очистка пользователей из `init_db()`;
bootstrap администратора остаётся. Добавлены тесты сохранности данных и повторного запуска.

## Доступы и секреты

| Конфигурация | Обращение при переносе |
| --- | --- |
| `TRAVELPAYOUTS_TOKEN` | Секрет; сохранить действующий до согласованной ротации |
| `TELEGRAM_BOT_TOKEN` | Секрет; не запускать два polling-процесса с одним токеном |
| `DATABASE_URL`, `POSTGRES_PASSWORD` | Секреты; новая отдельная роль, без доступа приложения к чужим БД |
| `SESSION_SECRET` | Секрет; смена делает существующие сессии и Telegram access links недействительными |
| `ADMIN_PASSWORD_HASH` | Секрет; bootstrap не заменяет пароль уже существующего пользователя в БД |
| SSH/TLS/registry credentials | Только operator secret store; не в образе/репозитории/логах |
| Partner marker и project IDs | Не секреты, но должны соответствовать площадке |
| `TELEGRAM_CHAT_ID` | Приватная runtime-конфигурация; не публиковать в документации |

Несекретные production-идентификаторы Travelpayouts:

```dotenv
TRAVELPAYOUTS_MARKER=740244
TRAVELPAYOUTS_WEBSITE_PROJECT_ID=540659
TRAVELPAYOUTS_TELEGRAM_PROJECT_ID=540302
```

GitHub repository: `AiRigaLabs01/TravellTickets`.
Проверка 2026-09-03: репозиторий private; `main` и `develop` возвращают
`protected=false`. Запрос rulesets возвращает 403 с ограничением текущего тарифа.
Это не ошибка токена: подключённый GitHub-доступ сообщает admin/push permissions.
Пока серверные ограничения недоступны, соблюдать PR-процесс операционно;
выбор тарифа/политики и уменьшение scopes доступа согласовать отдельно.
В организации Deploy Keys отключены (проверено в UI 2026-09-02).
Предпочтителен GitHub App с минимальными repository permissions и короткоживущими
installation tokens. Fine-grained PAT допустим только после выбора владельца,
точного репозитория, минимальных прав и срока действия.
Не менять политику организации ради legacy `git pull` на VPS: при deployment
по образам VPS нужен registry pull, а не доступ к исходникам GitHub.

Локальный `.env` и `operator/` исключены из Git. Проверка истории выполняется
`python scripts/check_secrets.py --history`; она печатает только путь, правило
и номер строки, без значений. Это ограниченный детектор известных форматов,
не гарантия отсутствия любых секретов. Отдельно проверить provider-side secret
scanning, владельцев, scopes, сроки и возможность отзыва каждого доступа.
При находке сначала согласовать ротацию, не переписывать Git-историю автоматически.

## Gates перед переносом

1. Merge подготовительного PR в `develop` после CI/review; release-PR в `main`
   охватывает всю накопленную историю продукта, не только affiliate-изменение.
2. Product CI: lint/tests, сборка из lock-файла и startup/HTTP smoke.
   Mypy имеет накопленный долг и остаётся advisory; не выдавать его за green gate.
3. Настроить отдельную публикацию release-образа в GHCR. Зафиксировать source SHA,
   digest, результаты проверок и предыдущий digest для rollback. Текущий CI
   ничего не публикует и не запускает platform rollout.
4. В platform-PR согласовать runtime schema, operator placement, env/secret store,
   PostgreSQL role/database, egress, edge/TLS renewal, probes, backup/restore и rollback.
   Пройти `make check` и platform preflight. Наличие записи в registry не равно готовому deploy.
5. Сделать защищённую резервную копию текущей БД и проверить восстановление в
   изолированной БД. Не подключать тестовый контейнер к production-БД.
6. Проверить новый image на восстановленной копии с отдельными тестовыми
   credentials или без интеграций: health, UI, auth, данные, повторный старт.
7. Согласовать окно переключения. Остановить старых writers (web, scheduler,
   polling), сделать финальную копию/синхронизацию БД. Только затем запускать
   новый production runtime и переключать согласованный edge/DNS.
8. Проверить публичный HTTPS, авторизацию, сохранность пользователей/маршрутов,
   новый поиск и партнёрную ссылку Aviasales (`aviasales.tpk.ro`), сохранённую ссылку
   Яндекса и одно согласованное Telegram-уведомление без дубликатов.
9. Старый стек не удалять до явного подтверждения. При rollback вернуть согласованный
   image/маршрутизацию; если на новом месте уже есть записи, сначала согласовать
   перенос данных назад. Нельзя просто запустить старую, устаревшую копию БД.
10. После приёмки передать платформе runbook и доступы, отключить legacy deploy,
    согласовать отзыв временных ключей и завершить перенос отдельным актом проверки.

## Не выполнено этим PR

- Изменение/ротация GitHub, SSH, Telegram, Travelpayouts или database credentials.
- Публикация образа, изменение прав/branch protection, merge release-PR.
- Изменение текущих правок платформы, перенос production, переключение DNS,
  отправка тестового сообщения пользователям или удаление старого стека.
