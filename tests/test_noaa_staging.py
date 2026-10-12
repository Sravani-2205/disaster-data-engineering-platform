"""
test_noaa_staging.py

Tests for stage_storm_events(). No mocking needed -- pure function,
deterministic small gzip-compressed CSV data built in-memory. No
network requests.
"""

import csv
import gzip
import io
from datetime import date

import pytest

from src.staging.noaa_staging import stage_storm_events


APPROVED_FIELDS = {
    "event_id",
    "episode_id",
    "state",
    "event_type",
    "cz_type",
    "cz_fips",
    "cz_name",
    "begin_date_time",
    "end_date_time",
    "cz_timezone",
    "injuries_direct",
    "injuries_indirect",
    "deaths_direct",
    "deaths_indirect",
    "damage_property",
    "damage_crops",
    "magnitude",
    "magnitude_type",
    "tor_f_scale",
    "begin_lat",
    "begin_lon",
    "end_lat",
    "end_lon",
    "source_file_year",
    "source_file_creation_date",
}


def _make_gzip_csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return gzip.compress(buffer.getvalue().encode("utf-8"))


FULL_HEADER = [
    "EVENT_ID", "EPISODE_ID", "STATE", "EVENT_TYPE", "CZ_TYPE", "CZ_FIPS",
    "CZ_NAME", "BEGIN_DATE_TIME", "END_DATE_TIME", "CZ_TIMEZONE",
    "INJURIES_DIRECT", "INJURIES_INDIRECT", "DEATHS_DIRECT", "DEATHS_INDIRECT",
    "DAMAGE_PROPERTY", "DAMAGE_CROPS", "MAGNITUDE", "MAGNITUDE_TYPE",
    "TOR_F_SCALE", "BEGIN_LAT", "BEGIN_LON", "END_LAT", "END_LON",
]


def test_valid_gzip_csv_produces_expected_staged_record():
    row = [
        "10001", "5001", "TEXAS", "Tornado", "C", "201", "TRAVIS",
        "01-JAN-19 14:00:00", "01-JAN-19 14:15:00", "CST-6",
        "2", "0", "1", "0", "10.00K", "5.00M", "1.5", "EG3", "F1",
        "30.27", "-97.74", "30.30", "-97.70",
    ]
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result == [{
        "event_id": "10001",
        "episode_id": "5001",
        "state": "TEXAS",
        "event_type": "Tornado",
        "cz_type": "C",
        "cz_fips": "201",
        "cz_name": "TRAVIS",
        "begin_date_time": "01-JAN-19 14:00:00",
        "end_date_time": "01-JAN-19 14:15:00",
        "cz_timezone": "CST-6",
        "injuries_direct": 2,
        "injuries_indirect": 0,
        "deaths_direct": 1,
        "deaths_indirect": 0,
        "damage_property": "10.00K",
        "damage_crops": "5.00M",
        "magnitude": 1.5,
        "magnitude_type": "EG3",
        "tor_f_scale": "F1",
        "begin_lat": 30.27,
        "begin_lon": -97.74,
        "end_lat": 30.30,
        "end_lon": -97.70,
        "source_file_year": 2019,
        "source_file_creation_date": date(2020, 2, 19),
    }]


def test_only_approved_curated_fields_are_present():
    row = ["10001"] + [""] * (len(FULL_HEADER) - 1)
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert set(result[0].keys()) == APPROVED_FIELDS


def test_blank_cells_become_none():
    row = [
        "10001", "", "TEXAS", "Tornado", "", "", "", "01-JAN-19 14:00:00",
        "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
    ]
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["episode_id"] is None
    assert result[0]["cz_type"] is None
    assert result[0]["end_date_time"] is None
    assert result[0]["magnitude"] is None
    assert result[0]["begin_lat"] is None
    # non-blank cells are unaffected
    assert result[0]["event_id"] == "10001"
    assert result[0]["state"] == "TEXAS"


def test_source_file_year_and_creation_date_attached():
    row = ["10001"] + [""] * (len(FULL_HEADER) - 1)
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2021, date(2022, 6, 1))

    assert result[0]["source_file_year"] == 2021
    assert result[0]["source_file_creation_date"] == date(2022, 6, 1)


def test_damage_strings_remain_unchanged():
    row = ["10001"] + [""] * 13 + ["10.00K", "5.00M"] + [""] * 7
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["damage_property"] == "10.00K"
    assert result[0]["damage_crops"] == "5.00M"


def test_datetime_strings_remain_unchanged():
    row = ["10001", "", "TEXAS", "Tornado", "", "", "", "01-JAN-19 14:00:00",
           "01-JAN-19 14:15:00", "CST-6"] + [""] * 13
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["begin_date_time"] == "01-JAN-19 14:00:00"
    assert result[0]["end_date_time"] == "01-JAN-19 14:15:00"
    assert result[0]["cz_timezone"] == "CST-6"


def test_multiple_csv_rows_produce_multiple_records():
    row_a = ["10001"] + [""] * (len(FULL_HEADER) - 1)
    row_b = ["10002"] + [""] * (len(FULL_HEADER) - 1)
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row_a, row_b])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert len(result) == 2
    assert result[0]["event_id"] == "10001"
    assert result[1]["event_id"] == "10002"


def test_corrupt_gzip_input_raises_and_does_not_silently_succeed():
    corrupt_bytes = b"this-is-not-gzip-data-at-all"

    with pytest.raises((OSError, gzip.BadGzipFile)):
        stage_storm_events(corrupt_bytes, 2019, date(2020, 2, 19))


def test_injury_and_death_values_become_python_int():
    row = ["10001", "", "TEXAS", "Tornado", "", "", "", "01-JAN-19 14:00:00",
           "", "", "3", "1", "0", "2"] + [""] * 9
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["injuries_direct"] == 3
    assert result[0]["injuries_indirect"] == 1
    assert result[0]["deaths_direct"] == 0
    assert result[0]["deaths_indirect"] == 2
    assert isinstance(result[0]["injuries_direct"], int)
    assert isinstance(result[0]["deaths_indirect"], int)


def test_magnitude_becomes_python_float():
    row = ["10001"] + [""] * 15 + ["1.5"] + [""] * 6
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["magnitude"] == 1.5
    assert isinstance(result[0]["magnitude"], float)


def test_lat_lon_values_become_python_float():
    row = ["10001"] + [""] * 18 + ["30.27", "-97.74", "30.30", "-97.70"]
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["begin_lat"] == 30.27
    assert result[0]["begin_lon"] == -97.74
    assert result[0]["end_lat"] == 30.30
    assert result[0]["end_lon"] == -97.70
    assert isinstance(result[0]["begin_lat"], float)
    assert isinstance(result[0]["end_lon"], float)


def test_blank_numeric_cells_become_none_not_zero():
    row = ["10001"] + [""] * (len(FULL_HEADER) - 1)
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["injuries_direct"] is None
    assert result[0]["magnitude"] is None
    assert result[0]["begin_lat"] is None


def test_malformed_numeric_string_is_preserved_not_dropped_or_nulled():
    """
    A non-blank value that fails int()/float() parsing must be kept
    as the original string so Stage D validation can reject it as
    invalid -- staging must not silently convert it to None.
    """
    row = ["10001"] + [""] * 15 + ["N/A"] + [""] * 6
    raw_bytes = _make_gzip_csv(FULL_HEADER, [row])

    result = stage_storm_events(raw_bytes, 2019, date(2020, 2, 19))

    assert result[0]["magnitude"] == "N/A"
