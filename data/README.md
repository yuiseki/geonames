---
license: cc-by-4.0
language:
- multilingual
task_categories:
- table-question-answering
- text-generation
tags:
- gazetteer
- geonames
- toponyms
- geospatial
- geoparquet
size_categories:
- 10M<n<100M
configs:
- config_name: 20261001.geoname
  data_files: parquet/20261001/geoname/*.parquet
  default: true
- config_name: 20261001.alternate_names
  data_files: parquet/20261001/alternate_names.parquet
- config_name: 20261001.hierarchy
  data_files: parquet/20261001/hierarchy.parquet
- config_name: 20261001.admin_code5
  data_files: parquet/20261001/admin_code5.parquet
---

# geonames

The GeoNames gazetteer, one night's dump at a time: 13.5 million named places
around the world, their 19 million alternate names in hundreds of languages,
the administrative hierarchy, and the small code tables, as GeoNames
published them, with Parquet beside them.

CC BY 4.0. Credit GeoNames (https://www.geonames.org/).

## Why dated snapshots

GeoNames rebuilds its dump every night at the same URLs, with no version
number or checksum, and keeps past versions only for paying subscribers. A
result computed on one day cannot be checked against the next. Each subset
here is named after the night it holds, `{snapshot}.{table}` as
`wikimedia/wikipedia` names its dumps, and a new night is added beside the
others; nothing already here changes.

| snapshot | allCountries.zip Last-Modified |
|---|---|
| `20261001` | Thu, 01 Oct 2026 02:08:51 GMT |

## What is in a snapshot

| table | rows (20261001) | |
|---|---:|---|
| `geoname` | 13,472,217 | the gazetteer, with a point `geometry` (GeoParquet) |
| `alternate_names` | 19,219,062 | names in other languages and forms, codes, links |
| `hierarchy` | 519,183 | parent and child, mostly administrative |
| `admin_code5` | 78,514 | the fifth administrative level, kept apart by GeoNames |

`raw/{snapshot}/` holds the files as GeoNames served them: allCountries.zip,
alternateNamesV2.zip, hierarchy.zip, adminCode5.zip, admin1CodesASCII.txt,
admin2Codes.txt, countryInfo.txt, featureCodes_en.txt, iso-languagecodes.txt,
timeZones.txt and readme.txt, with `MANIFEST.json` giving the URL, size,
sha256 and Last-Modified of each. The per-country zips and the cities files
are subsets of allCountries and are not kept.

`geoname` is four files cut between countries (`part-00` from the rows with
no country to FO, `part-01` FR to NL, `part-02` NO to UM, `part-03` US to
ZW), sorted by `country_code` and `geonameid`, so a query on one country
reads few row groups. `parquet/{snapshot}/outputs.json` lists the files with
their rows, sizes, sha256 and countries.

## Columns

The columns are those of GeoNames' readme.txt in snake case. `geonameid`,
`population`, `elevation` and `dem` are integers; `latitude` and `longitude`
floats; `modification_date` a date; everything else the text of the file, so
`admin1_code` `01` keeps its zero. The four `is_*` flags of the alternate
names, `'1'` or empty in the source, are booleans. A value that did not fit
would have stopped the build; none did. 623 names contain a double quote,
which is why the files are read with quoting off.

## Things to know

`admin1_code` is mostly FIPS, not ISO. Japan's prefectures run 01 Aichi to 47
Okinawa in Latin alphabetical order, not in the JIS order that starts with
Hokkaido.

`country_code` is empty for 7,112 rows: oceans, continents and other places
in no country. The rows with the largest `population` are Earth, Asia and the
Pacific Rim.

Japanese names are in `alternate_names`, not in `geoname.name`, which is
almost always Latin script. For Japan, 174,920 alternate names have
`isolanguage = 'ja'`, in kanji and kana mixed with nothing to tell them apart.

`isolanguage = 'wkdt'` rows hold Wikidata ids (1,111,651 of them), the key
for joining GeoNames to Wikidata; `link` rows hold URLs, mostly Wikipedia.

```sql
-- DuckDB, straight off the Hub: Kyoto city and its Japanese names
SELECT g.geonameid, g.name, a.alternate_name, a.is_preferred_name
FROM 'hf://datasets/yuiseki/geonames/parquet/20261001/geoname/part-01.parquet' g
JOIN 'hf://datasets/yuiseki/geonames/parquet/20261001/alternate_names.parquet' a USING (geonameid)
WHERE g.geonameid = 1857910 AND a.isolanguage = 'ja';
```

## Reproducing it

```bash
git clone https://github.com/yuiseki/geonames
cd geonames
uv run python scripts/01_download.py        # tonight's dump, as a new snapshot
uv run python scripts/03_export_parquet.py
uv run python scripts/02_verify.py
```

The dump of 20261001 was fetched on 2026-10-01 by another script and adopted
here with `01_download.py --from`, which copies a file only if it has the
size and sha256 recorded when it was fetched. The server is slow; that night
allCountries.zip took about 50 minutes.

## Licence

CC BY 4.0, as the dump's readme.txt says: "This work is licensed under a
Creative Commons Attribution 4.0 License". Credit GeoNames with a link or
another reference, for example:

    GeoNames (https://www.geonames.org/), CC BY 4.0

The files under `raw/` are GeoNames' own. The Parquet under `parquet/` is
made from them and changes their form, not their values; `LICENSE` beside
this file lists what was done.
