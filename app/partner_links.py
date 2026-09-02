import logging

import httpx

from app.config import (
    TRAVELPAYOUTS_LINKS_URL,
    TRAVELPAYOUTS_MARKER,
    TRAVELPAYOUTS_TOKEN,
)

logger = logging.getLogger(__name__)
MAX_LINKS_PER_REQUEST = 10


def _numeric_id(value: str) -> int | str:
    return int(value) if value.isdigit() else value


async def create_partner_links(urls: list[str], project_id: str, sub_id: str) -> list[str]:
    """Convert direct brand URLs to Travelpayouts partner URLs.

    Monitoring must remain useful if the affiliate API is unavailable, so a
    failed conversion falls back to the original URL instead of aborting the
    price check.
    """
    if not urls:
        return []
    if not (TRAVELPAYOUTS_TOKEN and TRAVELPAYOUTS_MARKER and project_id):
        return urls.copy()

    converted: list[str] = []
    headers = {"X-Access-Token": TRAVELPAYOUTS_TOKEN}
    async with httpx.AsyncClient(timeout=20) as client:
        for offset in range(0, len(urls), MAX_LINKS_PER_REQUEST):
            batch = urls[offset : offset + MAX_LINKS_PER_REQUEST]
            body = {
                "trs": _numeric_id(project_id),
                "marker": _numeric_id(TRAVELPAYOUTS_MARKER),
                "shorten": True,
                "links": [{"url": url, "sub_id": sub_id} for url in batch],
            }
            try:
                response = await client.post(TRAVELPAYOUTS_LINKS_URL, headers=headers, json=body)
                response.raise_for_status()
                items = response.json().get("result", {}).get("links", [])
                if len(items) != len(batch):
                    raise ValueError("Travelpayouts returned an unexpected number of links")
                converted.extend(
                    item.get("partner_url") if item.get("code") == "success" and item.get("partner_url") else original
                    for original, item in zip(batch, items)
                )
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                logger.warning("Could not create Travelpayouts partner links: %s", exc)
                converted.extend(batch)
    return converted


async def create_partner_link(url: str | None, project_id: str, sub_id: str) -> str:
    if not url:
        return ""
    return (await create_partner_links([url], project_id, sub_id))[0]
