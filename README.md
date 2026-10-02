# geonames

Dataset: https://huggingface.co/datasets/yuiseki/geonames

The GeoNames gazetteer kept one night at a time: each snapshot is that
night's dump, unchanged, with Parquet beside it, and the code that fetches,
checks and converts it. This repository holds the code; the data is on the
Hub.

## Where things are

```
scripts/01_download.py        tonight's dump as data/raw/<YYYYMMDD>/, or --from an earlier fetch
scripts/02_verify.py          every file against its MANIFEST.json; rows, Japan, size, no bloom filters
scripts/03_export_parquet.py  dump -> Parquet: typed by name, flags as booleans, gazetteer cut by country
src/publish.py                pushes the snapshots and the card to the Hub
tests/                        parsing, typing, splitting, snapshot names, adopting

data/README.md                the dataset card. Uploaded as-is; declare a new snapshot's subsets here
data/LICENSE                  CC BY 4.0 and what the Parquet changes
data/provenance.yaml          the snapshots, their counts, and what was done
data/raw/<YYYYMMDD>/          generated, about 630 MB a night, GeoNames' own files
data/parquet/<YYYYMMDD>/      generated, about 720 MB a night
```

## Adding a night

```sh
uv run python scripts/01_download.py      # about an hour; the server is slow
uv run python scripts/03_export_parquet.py
uv run python scripts/02_verify.py
# add the night's four subsets to data/README.md, and its counts to EXPECTED
uv run python src/publish.py --push
```

## Three traps

**Integers are checked before the cast.** DuckDB casts `'12.5'` to 13 when
asked for an INTEGER. Every integer column is matched against a pattern
first, so a value that does not fit stops the build.

**Quoting is off.** 623 names hold a double quote
(`Schronisko "Nad Śnieżnymi Kotłami"`). The files are tab separated with no
quoting, and a CSV reader with quoting on would join lines.

**alternateNamesV2.zip holds two files.** Besides alternateNamesV2.txt it has
a copy of iso-languagecodes.txt. The export takes the member named after the
zip.

## Licence

The code here is MIT. The data it fetches is CC BY 4.0, from GeoNames:

    GeoNames (https://www.geonames.org/), CC BY 4.0
