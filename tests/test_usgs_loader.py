"""
test_usgs_loader.py

Tests for load_records() against a real PostgreSQL test database
(disaster_data_test). Each test runs inside a rolled-back transaction
so no data persists between tests or into the real database.
"""

import os
from datetime import datetime, timezone

import psycopg
import pytest

from src.loading.usgs_loader import load_records, LoadError, LoadResult


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    # Ensure every test starts with a clean table. load_records()
    # commits its own transaction, so a teardown-only rollback can't
    # undo successful writes from a prior test -- we truncate up
    # front instead, and commit that truncate immediately.
    with connection.cursor() as cur:
        cur.execute("TRUNCATE earthquakes;")
    connection.commit()

    yield connection

    connection.rollback()  # discard anything left uncommitted by the test itself
    connection.close()


def make_record(**overrides):
    base = {
        "event_id": "test-event-1",
        "time": 1388620296020,
        "updated": 1388620296020,
        "magnitude": 1.29,
        "place": "10km SSW of Idyllwild, CA",
        "longitude": -116.7776667,
        "latitude": 33.6633333,
        "depth": 11.008,
    }
    base.update(overrides)
    return base


def fetch_row(conn, event_id, source="usgs"):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, updated, magnitude, place, depth, ingested_at "
            "FROM earthquakes WHERE source = %s AND event_id = %s",
            (source, event_id),
        )
        return cur.fetchone()


def test_insert_new_record(conn):
    result = load_records([make_record()], conn)

    assert result == LoadResult(inserted=1, updated=0, skipped=0)
    row = fetch_row(conn, "test-event-1")
    assert row is not None
    assert row[0] == "test-event-1"


def test_reload_identical_record_is_skipped(conn):
    record = make_record()
    load_records([record], conn)
    first_row = fetch_row(conn, "test-event-1")

    result = load_records([record], conn)

    assert result == LoadResult(inserted=0, updated=0, skipped=1)
    second_row = fetch_row(conn, "test-event-1")
    assert second_row == first_row  # nothing changed, including ingested_at


def test_reload_with_newer_updated_is_updated(conn):
    load_records([make_record(magnitude=1.29, updated=1000000000000)], conn)

    newer_record = make_record(magnitude=9.9, updated=2000000000000)
    result = load_records([newer_record], conn)

    assert result == LoadResult(inserted=0, updated=1, skipped=0)
    row = fetch_row(conn, "test-event-1")
    assert row[2] == 9.9  # magnitude updated


def test_reload_with_older_updated_is_skipped(conn):
    load_records([make_record(magnitude=9.9, updated=2000000000000)], conn)

    older_record = make_record(magnitude=1.29, updated=1000000000000)
    result = load_records([older_record], conn)

    assert result == LoadResult(inserted=0, updated=0, skipped=1)
    row = fetch_row(conn, "test-event-1")
    assert row[2] == 9.9  # unchanged, older data did not overwrite


def test_null_fields_load_as_sql_null(conn):
    record = make_record(magnitude=None, place=None, depth=None)

    load_records([record], conn)

    row = fetch_row(conn, "test-event-1")
    assert row[2] is None  # magnitude
    assert row[3] is None  # place
    assert row[4] is None  # depth


def test_mixed_batch_counts_are_correct(conn):
    load_records([make_record(event_id="existing-a", updated=1000000000000)], conn)

    batch = [
        make_record(event_id="new-b"),
        make_record(event_id="existing-a", updated=2000000000000, magnitude=5.0),
        make_record(event_id="existing-a", updated=500000000000, magnitude=1.0),
    ]
    # Note: last two both target "existing-a" -- second is an update,
    # third (older than what's now stored) should be skipped.
    result_1 = load_records([batch[0], batch[1]], conn)
    assert result_1 == LoadResult(inserted=1, updated=1, skipped=0)

    result_2 = load_records([batch[2]], conn)
    assert result_2 == LoadResult(inserted=0, updated=0, skipped=1)


def test_full_batch_idempotency(conn):
    records = [make_record(event_id=f"event-{i}") for i in range(5)]

    first = load_records(records, conn)
    assert first == LoadResult(inserted=5, updated=0, skipped=0)

    second = load_records(records, conn)
    assert second == LoadResult(inserted=0, updated=0, skipped=5)


def test_database_error_rolls_back_transaction(conn):
    # Force a failure: latitude outside the CHECK constraint range.
    bad_record = make_record(event_id="bad-event", latitude=999)

    with pytest.raises(LoadError):
        load_records([bad_record], conn)

    # Confirm nothing was written.
    row = fetch_row(conn, "bad-event")
    assert row is None
