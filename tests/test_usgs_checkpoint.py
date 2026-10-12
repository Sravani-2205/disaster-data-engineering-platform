"""
test_usgs_checkpoint.py

Tests for get_checkpoint() / advance_checkpoint() against a real
PostgreSQL test database (disaster_data_test). advance_checkpoint()
commits its own transaction, so -- same as the loader tests -- each
test truncates the checkpoint table up front rather than relying on
a teardown rollback.
"""

import os
from datetime import datetime, timezone

import psycopg
import pytest

from src.checkpointing.usgs_checkpoint import get_checkpoint, advance_checkpoint


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    with connection.cursor() as cur:
        cur.execute("TRUNCATE ingestion_checkpoints;")
    connection.commit()

    yield connection

    connection.rollback()
    connection.close()


def test_no_checkpoint_returns_none(conn):
    assert get_checkpoint(conn, source="usgs") is None


def test_advance_checkpoint_creates_row(conn):
    end_time = datetime(2014, 1, 2, tzinfo=timezone.utc)

    advance_checkpoint(conn, end_time, source="usgs")

    assert get_checkpoint(conn, source="usgs") == end_time


def test_read_after_write_matches_exactly(conn):
    end_time = datetime(2014, 3, 15, 12, 30, tzinfo=timezone.utc)

    advance_checkpoint(conn, end_time, source="usgs")
    result = get_checkpoint(conn, source="usgs")

    assert result == end_time


def test_advancing_existing_checkpoint_updates_not_duplicates(conn):
    first = datetime(2014, 1, 2, tzinfo=timezone.utc)
    second = datetime(2014, 1, 5, tzinfo=timezone.utc)

    advance_checkpoint(conn, first, source="usgs")
    advance_checkpoint(conn, second, source="usgs")

    assert get_checkpoint(conn, source="usgs") == second

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM ingestion_checkpoints WHERE source = %s",
            ("usgs",),
        )
        count = cur.fetchone()[0]
    assert count == 1  # updated in place, not duplicated


def test_checkpoint_unchanged_when_downstream_fails(conn):
    """
    Simulates the orchestration rule: advance_checkpoint() is simply
    never called when the load fails. This test proves the checkpoint
    module itself has no side effects unless explicitly invoked --
    the "not advancing" behavior is the absence of a call, not a
    special code path.
    """
    end_time = datetime(2014, 1, 2, tzinfo=timezone.utc)
    advance_checkpoint(conn, end_time, source="usgs")

    # Simulated failed run: no advance_checkpoint() call happens here.

    assert get_checkpoint(conn, source="usgs") == end_time  # unchanged


def test_zero_feature_window_can_still_advance(conn):
    """
    A window with zero earthquakes is still a successfully processed
    window -- the checkpoint module doesn't know or care how many
    records were involved, it just records the window's end_time.
    """
    end_time = datetime(2020, 6, 1, tzinfo=timezone.utc)

    advance_checkpoint(conn, end_time, source="usgs")

    assert get_checkpoint(conn, source="usgs") == end_time


def test_replaying_same_checkpoint_value_is_idempotent(conn):
    end_time = datetime(2014, 1, 2, tzinfo=timezone.utc)

    advance_checkpoint(conn, end_time, source="usgs")
    advance_checkpoint(conn, end_time, source="usgs")  # replay, same value

    assert get_checkpoint(conn, source="usgs") == end_time

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM ingestion_checkpoints WHERE source = %s",
            ("usgs",),
        )
        count = cur.fetchone()[0]
    assert count == 1


def test_multiple_sources_are_independent(conn):
    usgs_time = datetime(2014, 1, 2, tzinfo=timezone.utc)
    noaa_time = datetime(2020, 5, 1, tzinfo=timezone.utc)

    advance_checkpoint(conn, usgs_time, source="usgs")
    advance_checkpoint(conn, noaa_time, source="noaa")

    assert get_checkpoint(conn, source="usgs") == usgs_time
    assert get_checkpoint(conn, source="noaa") == noaa_time
