#!/usr/bin/env python3
"""Turn each dated GeoNames dump into Parquet, for the Hub viewer and DuckDB.

For every snapshot under data/raw/<YYYYMMDD>/ this writes, under
data/parquet/<YYYYMMDD>/:

  geoname/part-NN.parquet  the gazetteer (allCountries), a point geometry
                           added (GeoParquet), sorted by country and cut
                           between countries to stay well below 512 MB a file
  alternate_names.parquet  alternateNamesV2
  hierarchy.parquet
  admin_code5.parquet

Columns are named after readme.txt in snake case and typed: ids, population,
elevation and dem integers, latitude and longitude floats, modification_date
a date, the rest the text of the file. The four is_* flags of the alternate
names ('1' or empty) become booleans. A value that does not fit stops the
run; DuckDB's own cast would round '12.5' to 13. Every output's row count is
checked against the line count of its text file.

    uv run python scripts/03_export_parquet.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "parquet"
WORK = ROOT / "data" / "work"
# Readers that fetch over HTTP and caches in front of them do badly with files
# above 512 MB; every Parquet file must stay below it.
MAX_BYTES = 512 * 1024 * 1024

# columns as readme.txt lists them, in snake case
GEONAME = [
    ("geonameid", "BIGINT"), ("name", "VARCHAR"), ("asciiname", "VARCHAR"),
    ("alternatenames", "VARCHAR"), ("latitude", "DOUBLE"), ("longitude", "DOUBLE"),
    ("feature_class", "VARCHAR"), ("feature_code", "VARCHAR"), ("country_code", "VARCHAR"),
    ("cc2", "VARCHAR"), ("admin1_code", "VARCHAR"), ("admin2_code", "VARCHAR"),
    ("admin3_code", "VARCHAR"), ("admin4_code", "VARCHAR"), ("population", "BIGINT"),
    ("elevation", "INTEGER"), ("dem", "INTEGER"), ("timezone", "VARCHAR"),
    ("modification_date", "DATE"),
]  # fmt: skip
ALTERNATE_NAMES = [
    ("alternate_name_id", "BIGINT"), ("geonameid", "BIGINT"), ("isolanguage", "VARCHAR"),
    ("alternate_name", "VARCHAR"), ("is_preferred_name", "FLAG"), ("is_short_name", "FLAG"),
    ("is_colloquial", "FLAG"), ("is_historic", "FLAG"), ("from", "VARCHAR"), ("to", "VARCHAR"),
]  # fmt: skip
HIERARCHY = [("parent_id", "BIGINT"), ("child_id", "BIGINT"), ("type", "VARCHAR")]
ADMIN_CODE5 = [("geonameid", "BIGINT"), ("adm5code", "VARCHAR")]
# a part of geoname/ holds whole countries up to this many rows (about 300 MB)
GEONAME_PART_ROWS = 4_000_000


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def lines(path: Path) -> int:
    """Records in a GeoNames text file: one per line, a last line may lack its newline."""
    n, last = 0, b"\n"
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            n += block.count(b"\n")
            last = block[-1:]
    return n + (last != b"\n")


def select_sql(path: Path, columns: list[tuple[str, str]], geometry: bool = False) -> str:
    """A query reading one tab separated GeoNames file with the given column types.

    The files have no header and no quoting. FLAG columns hold '1' or nothing
    and become booleans; integers are checked before the cast, which would
    round '12.5' to 13 instead of failing.
    """
    raw = ", ".join(f"'c{i}': 'VARCHAR'" for i in range(len(columns)))
    src = (
        f"read_csv('{path}', delim = '\\t', header = false, quote = '', escape = '', "
        f"strict_mode = true, columns = {{{raw}}})"
    )
    exprs = []
    for i, (name, t) in enumerate(columns):
        c = f"c{i}"
        if t == "VARCHAR":
            e = c
        elif t == "FLAG":
            e = (
                f"case when {c} is null then false when {c} = '1' then true "
                f"else error('{path.name}: {name} is not ''1'' or empty: ' || {c}) end"
            )
        elif t in ("BIGINT", "INTEGER"):
            e = (
                f"case when {c} is null or regexp_full_match({c}, '-?[0-9]+') then cast({c} as {t}) "
                f"else error('{path.name}: {name} is not an integer: ' || {c}) end"
            )
        else:
            e = f"cast({c} as {t})"
        exprs.append(f'{e} as "{name}"')
    if geometry:
        exprs.append("st_point(cast(c5 as double), cast(c4 as double)) as geometry")
    return f"select {', '.join(exprs)} from {src}"


def split_points(counts: list[tuple[str, int]], max_rows: int) -> list[list[str]]:
    """Group sorted keys into parts of at most max_rows rows, never splitting a key."""
    parts: list[list[str]] = []
    size = 0
    for key, n in counts:
        if parts and size + n <= max_rows:
            parts[-1].append(key)
            size += n
        else:
            parts.append([key])
            size = n
    return parts


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def unzip_one(path: Path, out: Path) -> Path:
    """Extract the data file of a GeoNames zip, the one named after the zip.

    Beside it a zip may hold readme.txt or, in alternateNamesV2.zip, a copy of
    iso-languagecodes.txt.
    """
    want = path.stem + ".txt"
    with zipfile.ZipFile(path) as z:
        if want not in z.namelist():
            raise ValueError(f"{path.name} has no {want}: {z.namelist()}")
        return Path(z.extract(want, out))


def write_parquet(con, query: str, path: Path) -> dict:
    con.execute(
        f"copy ({query}) to '{path}' (format parquet, compression zstd, row_group_size 100000, write_bloom_filter false)"
    )
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise RuntimeError(f"{path.name}: {size} bytes, above the {MAX_BYTES} Cloudflare limit")
    rows = con.sql(f"select count(*) from '{path}'").fetchone()[0]
    return {"rows": rows, "bytes": size, "sha256": sha256(path)}


def build(raw: Path, work: Path) -> dict[str, dict]:
    con = duckdb.connect()
    con.execute("set memory_limit = '8GB'; set temp_directory = '" + str(work / "tmp") + "'")
    con.execute("install spatial; load spatial")
    text = work / "text"
    out: dict[str, dict] = {}

    f = unzip_one(raw / "allCountries.zip", text)
    expected = lines(f)
    con.execute(f"create table geoname as {select_sql(f, GEONAME, geometry=True)}")
    got = con.sql("select count(*) from geoname").fetchone()[0]
    if got != expected:
        raise RuntimeError(f"{f.name}: {got} rows read, the file has {expected} lines")
    counts = con.sql(
        "select coalesce(country_code, ''), count(*) from geoname group by 1 order by 1"
    ).fetchall()
    (work / "geoname").mkdir()
    total = 0
    for i, keys in enumerate(split_points(counts, GEONAME_PART_ROWS)):
        inlist = ", ".join(f"'{k}'" for k in keys)
        p = work / "geoname" / f"part-{i:02d}.parquet"
        info = write_parquet(
            con,
            f"select * from geoname where coalesce(country_code, '') in ({inlist}) "
            "order by country_code nulls first, geonameid",
            p,
        )
        out[f"geoname/{p.name}"] = info | {"countries": [keys[0], keys[-1]]}
        total += info["rows"]
        log(f"geoname/{p.name}: {info['rows']:,} rows, {keys[0] or '(none)'}..{keys[-1]}")
    if total != expected:
        raise RuntimeError(f"geoname parts hold {total} rows, {f.name} has {expected}")
    con.execute("drop table geoname")

    for zname, cols, order in [
        ("alternateNamesV2.zip", ALTERNATE_NAMES, "geonameid, alternate_name_id"),
        ("hierarchy.zip", HIERARCHY, "parent_id, child_id"),
        ("adminCode5.zip", ADMIN_CODE5, "geonameid"),
    ]:
        f = unzip_one(raw / zname, text)
        expected = lines(f)
        name = {"alternateNamesV2.zip": "alternate_names", "hierarchy.zip": "hierarchy",
                "adminCode5.zip": "admin_code5"}[zname]  # fmt: skip
        p = work / f"{name}.parquet"
        info = write_parquet(con, f"{select_sql(f, cols)} order by {order}", p)
        if info["rows"] != expected:
            raise RuntimeError(f"{p.name}: {info['rows']} rows, {f.name} has {expected} lines")
        out[p.name] = info
        log(f"{p.name}: {info['rows']:,} rows")
    return out


def main() -> int:
    for snap in sorted(p for p in RAW.iterdir() if p.is_dir()):
        out = OUT / snap.name
        if (out / "outputs.json").exists():
            log(f"{snap.name}: already built")
            continue
        work = WORK / snap.name
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        outputs = build(snap, work)
        shutil.rmtree(work / "text", ignore_errors=True)
        shutil.rmtree(work / "tmp", ignore_errors=True)
        out.mkdir(parents=True, exist_ok=True)
        for rel in outputs:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(work / rel), out / rel)
        (out / "outputs.json").write_text(json.dumps(outputs, indent=1))
        shutil.rmtree(work, ignore_errors=True)
        log(f"{snap.name}: {len(outputs)} Parquet files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
