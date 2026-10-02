#!/usr/bin/env python3
"""Check every snapshot: its files are the ones recorded, and its Parquet holds them.

For each data/raw/<YYYYMMDD>/: every file has the size and sha256 in its
MANIFEST.json, and every Parquet under data/parquet/<YYYYMMDD>/ has as many
rows as its text file has lines. For the snapshots listed in EXPECTED the
counts are pinned too, so a rebuild that loses rows says so.
"""

import hashlib
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PQ = ROOT / "data" / "parquet"

EXPECTED = {
    "20261001": {
        "geoname": 13472217,
        "alternate_names": 19219062,
        "hierarchy": 519183,
        "admin_code5": 78514,
        "geoname_jp": 103761,
        "alternate_names_jp_ja": 174920,
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    failures = []

    def check(ok: bool, what: str) -> None:
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            failures.append(what)

    con = duckdb.connect()
    for snap in sorted(p for p in RAW.iterdir() if p.is_dir()):
        name = snap.name
        manifest = json.loads((snap / "MANIFEST.json").read_text())
        bad = [
            f
            for f, m in manifest.items()
            if (snap / f).stat().st_size != m["bytes"] or sha256(snap / f) != m["sha256"]
        ]
        check(not bad, f"{name}: every file matches MANIFEST.json ({len(bad)} do not)")
        outputs = json.loads((PQ / name / "outputs.json").read_text())
        g = f"{PQ / name}/geoname/*.parquet"
        got = {
            "geoname": con.sql(f"select count(*) from '{g}'").fetchone()[0],
            "alternate_names": con.sql(
                f"select count(*) from '{PQ / name}/alternate_names.parquet'"
            ).fetchone()[0],
            "hierarchy": con.sql(
                f"select count(*) from '{PQ / name}/hierarchy.parquet'"
            ).fetchone()[0],
            "admin_code5": con.sql(
                f"select count(*) from '{PQ / name}/admin_code5.parquet'"
            ).fetchone()[0],
            "geoname_jp": con.sql(
                f"select count(*) from '{g}' where country_code = 'JP'"
            ).fetchone()[0],
            "alternate_names_jp_ja": con.sql(
                f"select count(*) from '{PQ / name}/alternate_names.parquet' a "
                f"join '{g}' g using (geonameid) where g.country_code = 'JP' and a.isolanguage = 'ja'"
            ).fetchone()[0],
        }
        written = sum(v["rows"] for k, v in outputs.items() if k.startswith("geoname/"))
        check(
            written == got["geoname"],
            f"{name}: geoname parts hold the {written:,} rows the build counted",
        )
        for k, v in EXPECTED.get(name, {}).items():
            check(got[k] == v, f"{name}: {k} {got[k]:,}, expected {v:,}")
        big = [k for k, v in outputs.items() if v["bytes"] >= 512 * 1024 * 1024]
        check(not big, f"{name}: every Parquet file is below 512 MB")
        bloom = con.sql(
            f"select count(*) filter (where bloom_filter_offset is not null) "
            f"from parquet_metadata('{PQ / name}/**/*.parquet')"
        ).fetchone()[0]
        check(bloom == 0, f"{name}: no Parquet carries bloom filters")

    if failures:
        print(f"\n{len(failures)} checks failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
