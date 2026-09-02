import asyncio

import app.partner_links as partner_links


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "result": {
                "links": [
                    {
                        "url": "https://www.aviasales.ru/search/MOW1009LED1",
                        "code": "success",
                        "partner_url": "https://aviasales.tpk.ro/example",
                    }
                ]
            }
        }


class _Client:
    def __init__(self, timeout: int):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _Response:
        assert url == partner_links.TRAVELPAYOUTS_LINKS_URL
        assert headers == {"X-Access-Token": "token"}
        assert json["trs"] == 540302
        assert json["marker"] == 740244
        assert json["links"][0]["sub_id"] == "telegram_alert"
        return _Response()


def test_create_partner_link(monkeypatch) -> None:
    monkeypatch.setattr(partner_links, "TRAVELPAYOUTS_TOKEN", "token")
    monkeypatch.setattr(partner_links, "TRAVELPAYOUTS_MARKER", "740244")
    monkeypatch.setattr(partner_links.httpx, "AsyncClient", _Client)

    result = asyncio.run(
        partner_links.create_partner_link(
            "https://www.aviasales.ru/search/MOW1009LED1",
            "540302",
            "telegram_alert",
        )
    )

    assert result == "https://aviasales.tpk.ro/example"
