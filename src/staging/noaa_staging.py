"""
noaa_staging.py

Responsibility: reshape a raw NOAA Storm Events Details gzip CSV
payload into a flat list of row-like dicts.

Type boundary: staging performs representation parsing only, not
data-quality validation. Blank cells become None. Integer fields
(injury/death counts) and numeric fields (magnitude, lat/lon) are
converted from their CSV string representation to Python int/float
when the value parses cleanly. All other curated fields (event_id,
state, damage strings, datetime strings, etc.) remain strings,
unchanged. If a numeric-field value is non-blank but cannot be
parsed (e.g. "N/A"), the original string is preserved as-is rather
than being converted to None or silently dropped -- Stage D
validation is responsible for rejecting it as non-numeric.
"""

import csv
import gzip
import io

# Fields converted from CSV string to Python int when non-blank and parseable.
_INTEGER_FIELDS = {"injuries_direct", "injuries_indirect", "deaths_direct", "deaths_indirect"}

# Fields converted from CSV string to Python float when non-blank and parseable.
_FLOAT_FIELDS = {"magnitude", "begin_lat", "begin_lon", "end_lat", "end_lon"}

# Maps the NOAA source CSV header (as published) to the approved
# curated staging field name.
_FIELD_MAP = {
    "EVENT_ID": "event_id",
    "EPISODE_ID": "episode_id",
    "STATE": "state",
    "EVENT_TYPE": "event_type",
    "CZ_TYPE": "cz_type",
    "CZ_FIPS": "cz_fips",
    "CZ_NAME": "cz_name",
    "BEGIN_DATE_TIME": "begin_date_time",
    "END_DATE_TIME": "end_date_time",
    "CZ_TIMEZONE": "cz_timezone",
    "INJURIES_DIRECT": "injuries_direct",
    "INJURIES_INDIRECT": "injuries_indirect",
    "DEATHS_DIRECT": "deaths_direct",
    "DEATHS_INDIRECT": "deaths_indirect",
    "DAMAGE_PROPERTY": "damage_property",
    "DAMAGE_CROPS": "damage_crops",
    "MAGNITUDE": "magnitude",
    "MAGNITUDE_TYPE": "magnitude_type",
    "TOR_F_SCALE": "tor_f_scale",
    "BEGIN_LAT": "begin_lat",
    "BEGIN_LON": "begin_lon",
    "END_LAT": "end_lat",
    "END_LON": "end_lon",
}


def stage_storm_events(
    raw_gzip_bytes: bytes,
    source_file_year: int,
    source_file_creation_date,
) -> list[dict]:
    """
    Decompress and parse a raw NOAA Storm Events Details gzip CSV
    payload into a flat list of curated dicts.

    Does not validate or reject records -- blank CSV cells become
    None, integer and numeric fields are parsed to Python int/float
    when non-blank and parseable, and every other value is passed
    through exactly as NOAA provided it. `source_file_year` and
    `source_file_creation_date` are attached to every record as file
    metadata.

    Raises:
        gzip.BadGzipFile / OSError: raw_gzip_bytes is not valid gzip.
    """
    decompressed = gzip.decompress(raw_gzip_bytes)
    text = decompressed.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    staged = []

    for row in reader:
        record = {}
        for source_column, staged_field in _FIELD_MAP.items():
            value = row.get(source_column)
            value = value if value not in (None, "") else None

            if value is not None and staged_field in _INTEGER_FIELDS:
                try:
                    value = int(value)
                except ValueError:
                    pass  # leave the original string; Stage D will reject it
            elif value is not None and staged_field in _FLOAT_FIELDS:
                try:
                    value = float(value)
                except ValueError:
                    pass  # leave the original string; Stage D will reject it

            record[staged_field] = value

        record["source_file_year"] = source_file_year
        record["source_file_creation_date"] = source_file_creation_date

        staged.append(record)

    return staged
