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

## Remaining release gates

This focused patch is not a completed audit of the whole release. Keep PR #2
open until the remaining checks are addressed:

- Review URL-bearing logs: Uvicorn/HAProxy access logging of `/tg/?token=...`,
  HTTPX INFO logging of Telegram API URLs, and raw exception messages. No real
  credentials were read or production logs inspected during this review.
- Harden login return URLs (`next_url.startswith('/')` also accepts `//host`)
  and test rate limiting against attacker-supplied `X-Forwarded-For` headers;
  document the exact trusted proxy boundary.
- Verify route edits/reset of cached results, concurrent checks/deletion, and
  backup restoration/first startup against an isolated PostgreSQL copy.
- Complete release CI/review and image-publication design before platform rollout.

Production, DNS, credentials and the platform repository were not modified.
