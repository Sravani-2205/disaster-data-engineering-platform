"""
test_validation_failures.py

Tests for persist_rejected_records() against a real PostgreSQL test
database (disaster_data_test). Commits its own transaction, so --
same as loader/checkpoint tests -- each test truncates the table
up front rather than relying on a teardown rollback.
"""

import os
from datetime import datetime, timezone, timedelta

import psycopg
import pytest

from src.quarantine.validation_failures import persist_rejected_records, QuarantineError
from src.validation.usgs_validation import RejectedRecord
from datetime import date, datetime, timezone, timedelta


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    with connection.cursor() as cur:
        cur.execute("TRUNCATE validation_failures;")
    connection.commit()

    yield connection

    connection.rollback()
    connection.close()


def fetch_all(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source, event_id, record, reasons, rejected_at "
            "FROM validation_failures ORDER BY id"
        )
        return cur.fetchall()


def test_empty_rejection_list_returns_zero_and_writes_nothing(conn):
    result = persist_rejected_records([], conn)

    assert result == 0
    assert fetch_all(conn) == []


def test_single_rejected_record_persists_all_fields(conn):
    rejected = RejectedRecord(
        record={"event_id": "abc", "latitude": 999},
        reasons=["latitude 999 is out of range (-90 to 90)"],
    )

    count = persist_rejected_records([rejected], conn, source="usgs")

    assert count == 1
    rows = fetch_all(conn)
    assert len(rows) == 1
    source, event_id, record, reasons, rejected_at = rows[0]
    assert source == "usgs"
    assert event_id == "abc"
    assert record == {"event_id": "abc", "latitude": 999}
    assert reasons == ["latitude 999 is out of range (-90 to 90)"]
    assert rejected_at is not None


def test_multiple_rejected_records_persist_independently(conn):
    rejected = [
        RejectedRecord(record={"event_id": "a"}, reasons=["reason a"]),
        RejectedRecord(record={"event_id": "b"}, reasons=["reason b"]),
        RejectedRecord(record={"event_id": "c"}, reasons=["reason c"]),
    ]

    count = persist_rejected_records(rejected, conn)

    assert count == 3
    rows = fetch_all(conn)
    assert len(rows) == 3
    assert [r[1] for r in rows] == ["a", "b", "c"]


def test_multiple_reasons_preserved_in_order(conn):
    rejected = RejectedRecord(
        record={"event_id": None, "latitude": 999, "longitude": 999},
        reasons=[
            "event_id is missing or empty",
            "latitude 999 is out of range (-90 to 90)",
            "longitude 999 is out of range (-180 to 180)",
        ],
    )

    persist_rejected_records([rejected], conn)

    rows = fetch_all(conn)
    assert rows[0][3] == [
        "event_id is missing or empty",
        "latitude 999 is out of range (-90 to 90)",
        "longitude 999 is out of range (-180 to 180)",
    ]


def test_missing_event_id_persists_as_sql_null(conn):
    rejected = RejectedRecord(
        record={"event_id": None, "latitude": 33.0},
        reasons=["event_id is missing or empty"],
    )

    persist_rejected_records([rejected], conn)

    rows = fetch_all(conn)
    assert rows[0][1] is None  # event_id column


def test_original_record_round_trips_exactly(conn):
    original = {
        "event_id": "xyz",
        "time": 1388620296020,
        "updated": 1457728844428,
        "magnitude": None,
        "place": None,
        "longitude": -116.7776667,
        "latitude": 33.6633333,
        "depth": None,
    }
    rejected = RejectedRecord(record=original, reasons=["magnitude is not numeric"])

    persist_rejected_records([rejected], conn)

    rows = fetch_all(conn)
    assert rows[0][2] == original  # exact dict equality, including None values


def test_none_values_preserved_as_json_null(conn):
    rejected = RejectedRecord(
        record={"event_id": "n1", "magnitude": None, "depth": None},
        reasons=["some reason"],
    )

    persist_rejected_records([rejected], conn)

    record = fetch_all(conn)[0][2]
    assert record["magnitude"] is None
    assert record["depth"] is None


def test_correct_source_stored(conn):
    rejected = RejectedRecord(record={"event_id": "s1"}, reasons=["x"])

    persist_rejected_records([rejected], conn, source="usgs")

    assert fetch_all(conn)[0][0] == "usgs"


def test_rejected_at_is_close_to_current_time(conn):
    rejected = RejectedRecord(record={"event_id": "t1"}, reasons=["x"])

    before = datetime.now(timezone.utc)
    persist_rejected_records([rejected], conn)
    after = datetime.now(timezone.utc)

    rejected_at = fetch_all(conn)[0][4]
    assert before - timedelta(seconds=5) <= rejected_at <= after + timedelta(seconds=5)


def test_replay_creates_duplicate_row_intentionally(conn):
    rejected = RejectedRecord(record={"event_id": "dup"}, reasons=["x"])

    persist_rejected_records([rejected], conn)
    persist_rejected_records([rejected], conn)  # replay

    rows = fetch_all(conn)
    assert len(rows) == 2  # both persisted, no dedup


def test_database_failure_rolls_back_transaction(conn):
    # Force a failure: reasons=None violates the NOT NULL constraint.
    rejected = RejectedRecord(record={"event_id": "bad"}, reasons=None)

    with pytest.raises(QuarantineError):
        persist_rejected_records([rejected], conn)

    assert fetch_all(conn) == []

def test_rejected_record_with_date_field_serializes_without_error(conn):
    """
    Regression test for the NOAA Stage F bug: source_file_creation_date
    is parsed to a Python `date` object during NOAA staging, which
    previously caused:
        TypeError: Object of type date is not JSON serializable
    when the shared quarantine module passed it straight to Jsonb().
    """
    rejected = RejectedRecord(
        record={
            "event_id": "noaa-1",
            "state": "TEXAS",
            "event_type": "Tornado",
            "begin_date_time": "01-JAN-19 00:00:00",
            "source_file_creation_date": date(2019, 1, 1),
        },
        reasons=["missing required field: episode_id"],
    )

    count = persist_rejected_records([rejected], conn, source="noaa")

    assert count == 1
    rows = fetch_all(conn)
    assert len(rows) == 1
    record = rows[0][2]
    assert record["source_file_creation_date"] == "2019-01-01"
    assert record["event_id"] == "noaa-1"