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

Production, DNS, credentials and the platform repository were not modified.
