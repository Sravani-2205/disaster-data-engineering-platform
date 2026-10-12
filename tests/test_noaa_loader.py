"""
test_noaa_loader.py

Tests for load_records() (NOAA) against a real PostgreSQL test
database (disaster_data_test). load_records() commits its own
transaction, so each test truncates storm_events up front (and
commits that truncate) rather than relying solely on a teardown
rollback -- same convention as test_usgs_loader.py.
"""

import os
from datetime import date, datetime, timezone

import psycopg
import pytest

from src.loading.noaa_loader import load_records, LoadError, LoadResult


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    with connection.cursor() as cur:
        cur.execute("TRUNCATE storm_events;")
    connection.commit()

    yield connection

    connection.rollback()
    connection.close()


def make_record(**overrides):
    base = {
        "event_id": "test-event-1",
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
    }
    base.update(overrides)
    return base


def fetch_row(conn, event_id, source="noaa"):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, magnitude, damage_property, damage_crops, "
            "begin_date_time, source_file_creation_date, source_file_year, "
            "injuries_direct, begin_lat, ingested_at "
            "FROM storm_events WHERE source = %s AND event_id = %s",
            (source, event_id),
        )
        return cur.fetchone()


def test_insert_new_record(conn):
    result = load_records([make_record()], conn)

    assert result == LoadResult(inserted=1, updated=0, skipped=0)
    row = fetch_row(conn, "test-event-1")
    assert row is not None
    assert row[0] == "test-event-1"


def test_reload_same_file_revision_is_skipped(conn):
    record = make_record()
    load_records([record], conn)
    first_row = fetch_row(conn, "test-event-1")

    result = load_records([record], conn)

    assert result == LoadResult(inserted=0, updated=0, skipped=1)
    second_row = fetch_row(conn, "test-event-1")
    assert second_row == first_row  # nothing changed, including ingested_at


def test_reload_with_newer_file_revision_is_updated(conn):
    load_records(
        [make_record(magnitude=1.5, source_file_creation_date=date(2020, 2, 19))],
        conn,
    )

    newer_record = make_record(
        magnitude=9.9, source_file_creation_date=date(2020, 3, 1)
    )
    result = load_records([newer_record], conn)

    assert result == LoadResult(inserted=0, updated=1, skipped=0)
    row = fetch_row(conn, "test-event-1")
    assert row[1] == 9.9  # magnitude updated
    assert row[5] == date(2020, 3, 1)  # source_file_creation_date updated


def test_reload_with_older_file_revision_is_skipped(conn):
    load_records(
        [make_record(magnitude=9.9, source_file_creation_date=date(2020, 3, 1))],
        conn,
    )

    older_record = make_record(
        magnitude=1.5, source_file_creation_date=date(2020, 2, 19)
    )
    result = load_records([older_record], conn)

    assert result == LoadResult(inserted=0, updated=0, skipped=1)
    row = fetch_row(conn, "test-event-1")
    assert row[1] == 9.9  # unchanged, older revision did not overwrite
    assert row[5] == date(2020, 3, 1)  # creation date unchanged


def test_null_optional_fields_load_as_sql_null(conn):
    record = make_record(
        magnitude=None,
        begin_lat=None,
        begin_lon=None,
        end_lat=None,
        end_lon=None,
        injuries_direct=None,
        injuries_indirect=None,
        deaths_direct=None,
        deaths_indirect=None,
        episode_id=None,
        cz_type=None,
        end_date_time=None,
    )

    load_records([record], conn)

    row = fetch_row(conn, "test-event-1")
    assert row[1] is None  # magnitude
    assert row[7] is None  # injuries_direct
    assert row[8] is None  # begin_lat


def test_damage_strings_load_unchanged(conn):
    record = make_record(damage_property="10.00K", damage_crops="5.00M")

    load_records([record], conn)

    row = fetch_row(conn, "test-event-1")
    assert row[2] == "10.00K"
    assert row[3] == "5.00M"


def test_datetime_strings_load_unchanged(conn):
    record = make_record(begin_date_time="01-JAN-19 14:00:00")

    load_records([record], conn)

    row = fetch_row(conn, "test-event-1")
    assert row[4] == "01-JAN-19 14:00:00"


def test_mixed_batch_counts_are_correct(conn):
    load_records(
        [make_record(
            event_id="existing-a", source_file_creation_date=date(2020, 1, 1)
        )],
        conn,
    )

    result_1 = load_records(
        [
            make_record(event_id="new-b"),
            make_record(
                event_id="existing-a",
                source_file_creation_date=date(2020, 3, 1),
                magnitude=5.0,
            ),
        ],
        conn,
    )
    assert result_1 == LoadResult(inserted=1, updated=1, skipped=0)

    result_2 = load_records(
        [make_record(
            event_id="existing-a",
            source_file_creation_date=date(2020, 2, 1),
            magnitude=1.0,
        )],
        conn,
    )
    assert result_2 == LoadResult(inserted=0, updated=0, skipped=1)


def test_full_batch_idempotency(conn):
    records = [make_record(event_id=f"event-{i}") for i in range(5)]

    first = load_records(records, conn)
    assert first == LoadResult(inserted=5, updated=0, skipped=0)

    second = load_records(records, conn)
    assert second == LoadResult(inserted=0, updated=0, skipped=5)


def test_database_error_rolls_back_transaction(conn):
    # Force a failure: begin_lat outside the CHECK constraint range.
    bad_record = make_record(event_id="bad-event", begin_lat=999.0)

    with pytest.raises(LoadError):
        load_records([bad_record], conn)

    row = fetch_row(conn, "bad-event")
    assert row is None


def test_source_defaults_to_noaa(conn):
    load_records([make_record()], conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT source FROM storm_events WHERE event_id = %s",
            ("test-event-1",),
        )
        row = cur.fetchone()
    assert row[0] == "noaa"


def test_ingested_at_set_once_per_call_in_utc(conn):
    before = datetime.now(timezone.utc)
    load_records([make_record()], conn)
    after = datetime.now(timezone.utc)

    row = fetch_row(conn, "test-event-1")
    ingested_at = row[9]

    assert before <= ingested_at <= after
