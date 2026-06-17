from __future__ import annotations

import csv
import html
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


SOURCE_URL = "https://btgroupe.ru/poleznaya-informaciya/aeroporty-rossii/"
OUTPUT_PATH = Path("data/russian_airports.tsv")
USER_AGENT = "Mozilla/5.0 (compatible; TravellTickets/1.0)"
OUTPUT_COLUMNS = ["Код_ИАТА", "Внутр._код", "Населённый_пункт", "Регион", "Название_аэропорта"]
SOURCE_COLUMNS = {
    "Код_ИАТА": "Код ИАТА",
    "Внутр._код": "Внутр. код",
    "Населённый_пункт": "Населённый пункт",
    "Регион": "Регион",
    "Название_аэропорта": "Название аэропорта",
}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self._table: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._table = []
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(_clean_text("".join(self._cell)))
            self._in_cell = False
        elif tag == "tr" and self._in_table:
            if self._row:
                self._table.append(self._row)
        elif tag == "table" and self._in_table:
            self.tables.append(self._table)
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _clean_text(value: str) -> str:
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def _download_source() -> str:
    request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _extract_airport_rows(source_html: str) -> list[dict[str, str]]:
    parser = TableParser()
    parser.feed(source_html)
    for table in parser.tables:
        if not table:
            continue
        header = table[0]
        if all(column in header for column in SOURCE_COLUMNS.values()):
            index = {name: header.index(name) for name in SOURCE_COLUMNS.values()}
            return [
                {
                    output_name: row[index[source_name]] if len(row) > index[source_name] else ""
                    for output_name, source_name in SOURCE_COLUMNS.items()
                }
                for row in table[1:]
            ]
    raise RuntimeError("Airport table with expected columns was not found")


def write_tsv(rows: list[dict[str, str]], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = _extract_airport_rows(_download_source())
    write_tsv(rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
