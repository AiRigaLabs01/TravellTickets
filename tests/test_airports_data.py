import csv
from pathlib import Path


AIRPORTS_PATH = Path("data/russian_airports.tsv")
EXPECTED_HEADER = ["Код_ИАТА", "Внутр._код", "Населённый_пункт", "Регион", "Название_аэропорта"]


def test_russian_airports_tsv_shape_and_key_codes() -> None:
    with AIRPORTS_PATH.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))

    assert rows
    assert list(rows[0].keys()) == EXPECTED_HEADER
    by_iata = {row["Код_ИАТА"]: row for row in rows if row["Код_ИАТА"]}

    assert by_iata["SVO"]["Внутр._код"] == "ШРМ"
    assert by_iata["DME"]["Внутр._код"] == "ДМД"
    assert by_iata["VKO"]["Внутр._код"] == "ВНК"
    assert by_iata["SVX"]["Внутр._код"] == "КЛЦ"
