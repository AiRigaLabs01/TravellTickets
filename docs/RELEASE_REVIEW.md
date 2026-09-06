# Release review: develop -> main

## 2026-09-03: Telegram access boundary

Release PR #2 contains the accumulated application, not just the platform
preparation. The first focused review found three access/privacy defects:

1. Both the bot and web repository granted access by matching a mutable Telegram
   username, even when the route belonged to a different chat. A reassigned
   username could expose another chat's routes and bot management actions.
2. Private `/tg/` pages loaded a third-party script while their URL contained a
   bearer token. The referrer policy also permitted sending the full URL to
   HTTPS destinations. The legacy HAProxy overrode the application policy.
3. A token restricted to one route was not restricted when used on the list page.

Regression tests reproduced these problems before the fix. Access now uses only
the stored chat ID, and the optional route ID is enforced by the shared query.
Private pages no longer load partner JavaScript, use `Cache-Control: no-store`,
and send `Referrer-Policy: no-referrer`. Legacy HAProxy uses the same policy.
Explicit Aviasales/Yandex affiliate links and the public-page script remain.

### Compatibility and rollout

- No schema migration or credential rotation is performed.
- Routes with only a username and no verified chat binding are deliberately not
  visible through Telegram. An administrator must verify their owner before
  assigning `telegram_chat_id`; do not bulk-bind by username.
- Existing chat-wide links remain chat-wide. Route-specific links show only
  their route, including when navigating back to the monitoring list.
- Bot authorization remains chat-scoped: this change does not introduce
  per-member permissions for group chats.
- Deploy both application and edge referrer-policy changes. The new platform
  edge must not restore `no-referrer-when-downgrade`.
- Tokens previously exposed to an external party or logs are not revoked by
  this patch. Agree on expiry/rotation separately if an exposure is confirmed.

## 2026-09-03: HTTP and log hardening

- Login redirects now accept only unambiguous local paths. Regression tests
  reproduced the external `//host` redirect and header-spoofed login limit bypass.
- Rate limiting uses the ASGI client address, not raw forwarded headers. Uvicorn
  processes forwarding only from explicitly trusted peers (`FORWARDED_ALLOW_IPS`).
- Legacy HAProxy overwrites X-Forwarded-For with the actual socket source and
  already overwrites X-Forwarded-Proto. If a CDN is added, its trust chain needs
  a separate reviewed configuration; this config assumes a public-facing edge.
- Python log handlers redact query strings, recognizable Telegram bot tokens,
  and configured secret values after formatting (including exception text).
  If logging handlers are replaced at runtime, reinstall the redaction wrapper.
  Arbitrary prints/third-party telemetry are not covered. No historical logs
  were read, modified or claimed safe; existing exposure needs separate review.
- HAProxy logs method/path/status/timing without query strings or cookies.
  The `%HP` field is documented in the
  [HAProxy 2.9 manual](https://docs.haproxy.org/2.9/configuration.html#8.2.6).
  CI validates the actual config with disposable TLS material and checks that
  the application's access log does not expose a synthetic query token.
- Telegram API error logs no longer include raw response bodies or exception
  messages. HTTPS APP_BASE_URL keeps the login cookie Secure even if forwarding
  trust has not yet been configured.

### Required operator configuration (not changed by this PR)

Set `FORWARDED_ALLOW_IPS` to exact edge addresses, or a dedicated proxy-only
network CIDR; never `*` or a shared container network. Restrict application port
5000 to those peers. The example defaults to loopback only: until configured,
all users behind an untrusted proxy share its rate-limit bucket, by design.
Set production APP_BASE_URL to its HTTPS URL. Apply HAProxy changes together
with the application and preserve these policies in AI_Service_Platform.
Validate client-IP separation and Secure cookies in an isolated deployment
before production rollout; no live proxy IPs were inferred or changed here.

## Remaining release gates

This focused patch is not a completed audit of the whole release. Keep PR #2
open until the remaining checks are addressed:

- Accept the HTTP/log hardening PR after CI and review. Separately verify
  runtime proxy trust and decide whether historical logs require an exposure
  audit or credential rotation through the approved operator workflow.
- Verify route edits/reset of cached results, concurrent checks/deletion, and
  backup restoration/first startup against an isolated PostgreSQL copy.
- Complete release CI/review and image-publication design before platform rollout.

## PostgreSQL backup/restore rehearsal

CI starts a disposable PostgreSQL 16 service, seeds linked user, route, price
check and notification records, and creates a native custom-format `pg_dump`.
It validates the archive, restores it into a second empty database, then checks:

- data values and foreign-key relationships survived;
- `init_db()` remains idempotent across two starts after restore;
- PostgreSQL sequences continue without primary-key collisions.

The rehearsal script has an independent fail-closed guard: it runs only with an
explicit flag, the dedicated CI role, a loopback database host, and one of two
fixed CI database names. It refuses production-looking and remote URLs. The CI
credentials and databases are synthetic and ephemeral.

This proves the release backup/restore procedure against generated representative
data. It does not read production credentials, inspect production data, or replace
the required production backup and restore verification during the approved
migration window.

## 2026-09-06: CI annotations and typing gate

- GitHub-maintained checkout/setup-python actions now use immutable commits for
  v6 releases backed by Node.js 24. This removes the Node.js 20 deprecation
  annotations without floating mutable tags.
- SQLAlchemy models use typed `Mapped` declarations. A PostgreSQL DDL snapshot
  regression test proves that the typing-only conversion does not alter tables,
  columns, indexes, constraints or nullability.
- The 111 application type errors are resolved. `mypy app` is now a blocking CI
  step; `continue-on-error` was removed. APScheduler 3.x lacks distributed type
  metadata, so only imports from `apscheduler.*` have a narrow missing-import
  exception. No application module or error category is globally suppressed.
- Date helpers now declare the string input they already supported. Telegram
  handlers accept messages without text, and an unbound route cannot generate
  a Telegram access link.

The next CI run must finish without a type-check error or Node.js 20 warning.

Production, DNS, credentials and the platform repository were not modified.

## 2026-09-06: immutable release image contract

- `.github/workflows/publish-image.yml` runs only from `main` (including manual
  dispatch) and uses the repository-scoped `GITHUB_TOKEN` to publish to GHCR.
- The exact image is smoke-tested before publication without production
  credentials. It is tagged `sha-<source commit>` and records OCI source and
  revision labels. No mutable `latest` tag is produced.
- The workflow records the registry digest in its run summary. The platform must
  deploy `ghcr.io/airigalabs01/travelltickets@sha256:<digest>`, never the tag.
- Publication does not connect to a VPS, change DNS, or start a deployment.
- GitHub artifact attestations are not enabled: for a private repository GitHub
  requires Enterprise Cloud. Traceability therefore relies on the workflow run,
  source SHA, OCI labels, SHA tag and registry digest.

Before platform rollout, record the successful publication run, its source SHA,
the new digest and the previous production digest. Verify a selected image with:

```console
docker pull ghcr.io/airigalabs01/travelltickets@sha256:<digest>
docker image inspect ghcr.io/airigalabs01/travelltickets@sha256:<digest>
```

This change configures future publication. It does not publish an image until
the release PR reaches `main`; production remains unchanged.
