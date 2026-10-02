import importlib.util
from pathlib import Path

import duckdb
import pytest

_spec = importlib.util.spec_from_file_location(
    "export", Path(__file__).parents[1] / "scripts" / "03_export_parquet.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

KYOTO = (
    "1857910\tKyoto\tKyoto\tKyōto-shi,京都市\t35.02107\t135.75385\tP\tPPLA\tJP\t\t22\t"
    "1857907\t26100\t\t1459640\t\t50\tAsia/Tokyo\t2024-06-11\n"
)


def _con():
    con = duckdb.connect()
    con.execute("install spatial; load spatial")
    return con


def test_lines_counts_records(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"1\ta\n2\tb\n")
    assert m.lines(f) == 2


def test_lines_counts_a_last_line_without_newline(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"1\ta\n2\tb")
    assert m.lines(f) == 2


def test_geoname_types_and_geometry(tmp_path):
    f = tmp_path / "allCountries.txt"
    f.write_text(KYOTO, encoding="utf-8")
    rel = _con().sql(m.select_sql(f, m.GEONAME, geometry=True))
    row = dict(zip(rel.columns, rel.fetchone(), strict=True))
    assert row["geonameid"] == 1857910
    assert row["alternatenames"] == "Kyōto-shi,京都市"
    assert row["admin1_code"] == "22" and row["admin3_code"] == "26100"
    assert row["admin4_code"] is None
    assert row["population"] == 1459640 and row["elevation"] is None and row["dem"] == 50
    assert str(row["modification_date"]) == "2024-06-11"
    types = dict(zip(rel.columns, rel.types, strict=True))
    assert types["latitude"] == "DOUBLE" and types["admin2_code"] == "VARCHAR"
    assert rel.select("st_astext(geometry)").fetchone() == ("POINT (135.75385 35.02107)",)


def test_quotes_in_a_name_are_kept_as_text(tmp_path):
    f = tmp_path / "allCountries.txt"
    f.write_text(KYOTO.replace("\tKyoto\tKyoto\t", '\t"Kyoto" \'x\tKyoto\t'), encoding="utf-8")
    rel = _con().sql(m.select_sql(f, m.GEONAME))
    assert rel.select("name").fetchone() == ('"Kyoto" \'x',)


def test_alternate_name_flags_become_booleans(tmp_path):
    f = tmp_path / "alternateNamesV2.txt"
    f.write_text("1\t1857910\tja\t京都市\t1\t\t\t\t\t\n2\t1857910\tja\tきょうとし\t\t\t\t1\t\t\n")
    rel = _con().sql(m.select_sql(f, m.ALTERNATE_NAMES))
    got = rel.select("alternate_name, is_preferred_name, is_historic").order("1").fetchall()
    assert got == [("きょうとし", False, True), ("京都市", True, False)]


def test_an_unexpected_flag_value_stops_the_run(tmp_path):
    f = tmp_path / "alternateNamesV2.txt"
    f.write_text("1\t1857910\tja\t京都市\t0\t\t\t\t\t\n")
    with pytest.raises(duckdb.Error, match="is_preferred_name is not '1' or empty: 0"):
        _con().sql(m.select_sql(f, m.ALTERNATE_NAMES)).fetchall()


def test_a_non_integer_stops_the_run(tmp_path):
    f = tmp_path / "allCountries.txt"
    f.write_text(KYOTO.replace("\t1459640\t", "\t1459640.5\t"), encoding="utf-8")
    with pytest.raises(duckdb.Error, match="population is not an integer: 1459640.5"):
        _con().sql(m.select_sql(f, m.GEONAME)).fetchall()


def test_split_points_cut_by_key_without_splitting_a_key():
    counts = [("AD", 10), ("AE", 30), ("JP", 50), ("US", 40), ("ZW", 10)]
    parts = m.split_points(counts, max_rows=60)
    assert parts == [["AD", "AE"], ["JP"], ["US", "ZW"]]


def test_split_points_keeps_a_key_bigger_than_the_limit_whole():
    assert m.split_points([("US", 100), ("ZW", 1)], max_rows=60) == [["US"], ["ZW"]]


def _zip(path: Path, name: str, text: str) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "readme")
        z.writestr(name, text)


def test_unzip_one_takes_the_file_named_after_the_zip(tmp_path):
    import zipfile

    p = tmp_path / "alternateNamesV2.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("iso-languagecodes.txt", "codes")
        z.writestr("alternateNamesV2.txt", "names")
    assert m.unzip_one(p, tmp_path / "out").read_text() == "names"


def test_unzip_one_rejects_a_zip_without_the_named_file(tmp_path):
    import zipfile

    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("a.txt", "1")
        z.writestr("b.txt", "2")
    with pytest.raises(ValueError, match="has no x.txt"):
        m.unzip_one(p, tmp_path)


def test_build_cuts_the_gazetteer_between_countries(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    jp = KYOTO
    us = KYOTO.replace("1857910", "5128581").replace("\tJP\t", "\tUS\t")
    nocountry = KYOTO.replace("1857910", "1").replace("\tJP\t", "\t\t")
    _zip(
        raw / "allCountries.zip",
        "allCountries.txt",
        jp + us + us.replace("5128581", "5128582") + nocountry,
    )
    _zip(
        raw / "alternateNamesV2.zip",
        "alternateNamesV2.txt",
        "1\t1857910\tja\t京都市\t1\t\t\t\t\t\n",
    )
    _zip(raw / "hierarchy.zip", "hierarchy.txt", "6295630\t6255146\tADM\n")
    _zip(raw / "adminCode5.zip", "adminCode5.txt", "1193247\t13609633\n")
    monkeypatch.setattr(m, "GEONAME_PART_ROWS", 2)
    work = tmp_path / "work"
    work.mkdir()
    out = m.build(raw, work)
    parts = {k: v for k, v in out.items() if k.startswith("geoname/")}
    assert {k: (v["rows"], v["countries"]) for k, v in parts.items()} == {
        "geoname/part-00.parquet": (2, ["", "JP"]),
        "geoname/part-01.parquet": (2, ["US", "US"]),
    }
    assert out["alternate_names.parquet"]["rows"] == 1
    assert out["hierarchy.parquet"]["rows"] == 1 and out["admin_code5.parquet"]["rows"] == 1
    con = duckdb.connect()
    ids = con.sql(f"select geonameid from '{work}/geoname/part-00.parquet'").fetchall()
    assert ids == [(1,), (1857910,)]
