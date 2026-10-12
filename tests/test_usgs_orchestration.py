"""
test_usgs_orchestration.py

Tests for run_usgs_pipeline(). fetch_earthquake_data is mocked (no
real HTTP); everything else (staging, validation, loading,
checkpointing) runs for real against disaster_data_test, so these
tests exercise the actual sequencing and idempotency guarantees.
"""

import os
from datetime import datetime, timezone
from unittest.mock import patch

import psycopg
import pytest

from src.orchestration.usgs_pipeline import run_usgs_pipeline
from src.checkpointing.usgs_checkpoint import get_checkpoint
from src.loading.usgs_loader import LoadError


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    with connection.cursor() as cur:
        cur.execute("TRUNCATE earthquakes;")
        cur.execute("TRUNCATE ingestion_checkpoints;")
        cur.execute("TRUNCATE validation_failures;")
    connection.commit()

    yield connection

    connection.rollback()
    connection.close()


def make_feature(event_id, updated_millis, magnitude=1.0):
    return {
        "id": event_id,
        "properties": {
            "time": 1388620296020,
            "updated": updated_millis,
            "mag": magnitude,
            "place": "Somewhere",
        },
        "geometry": {"coordinates": [-116.0, 33.0, 10.0]},
    }


def make_payload(*features):
    return {"metadata": {"count": len(features)}, "features": list(features)}


PATCH_TARGET = "src.orchestration.usgs_pipeline.fetch_earthquake_data"


@patch(PATCH_TARGET)
def test_first_run_without_checkpoint_requires_historical_start_time(mock_fetch, conn):
    with pytest.raises(ValueError):
        run_usgs_pipeline(conn, historical_start_time=None, end_time="2014-01-02")

    mock_fetch.assert_not_called()


@patch(PATCH_TARGET)
def test_first_run_with_historical_start_time_advances_checkpoint(mock_fetch, conn):
    mock_fetch.return_value = make_payload(make_feature("a", 1000000000000))

    result = run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )

    mock_fetch.assert_called_once_with(
        "2014-01-01", "2014-01-02T00:00:00+00:00", updated_after=None
    )
    assert result.inserted == 1
    assert result.checkpoint_advanced_to == datetime(2014, 1, 2, tzinfo=timezone.utc)
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)


@patch(PATCH_TARGET)
def test_second_run_uses_checkpoint_as_updated_after(mock_fetch, conn):
    mock_fetch.return_value = make_payload(make_feature("a", 1000000000000))
    run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )

    mock_fetch.return_value = make_payload(make_feature("b", 1100000000000))
    run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-03T00:00:00+00:00"
    )

    second_call_kwargs = mock_fetch.call_args.kwargs
    assert second_call_kwargs["updated_after"] == "2014-01-02T00:00:00+00:00"


@patch(PATCH_TARGET)
def test_fetch_failure_leaves_checkpoint_unchanged(mock_fetch, conn):
    from src.ingestion.usgs_client import USGSRequestError

    mock_fetch.side_effect = USGSRequestError("simulated network failure")

    with pytest.raises(USGSRequestError):
        run_usgs_pipeline(
            conn, historical_start_time="2014-01-01", end_time="2014-01-02"
        )

    assert get_checkpoint(conn, "usgs") is None


@patch("src.orchestration.usgs_pipeline.load_records")
@patch(PATCH_TARGET)
def test_load_failure_leaves_checkpoint_unchanged(mock_fetch, mock_load, conn):
    """
    Forces the failure at the loader boundary directly (mocking
    load_records), rather than via a bad value in the payload --
    a bad latitude, for instance, is caught by Python validation
    before it ever reaches the loader, so it can't exercise this
    path. This test is specifically about orchestration's reaction
    to a LoadError, not the loader's own behavior (already covered
    in test_usgs_loader.py).
    """
    mock_fetch.return_value = make_payload(make_feature("a", 1000000000000))
    mock_load.side_effect = LoadError("simulated database failure")

    with pytest.raises(LoadError):
        run_usgs_pipeline(
            conn, historical_start_time="2014-01-01", end_time="2014-01-02"
        )

    assert get_checkpoint(conn, "usgs") is None


@patch(PATCH_TARGET)
def test_zero_feature_response_still_advances_checkpoint(mock_fetch, conn):
    mock_fetch.return_value = make_payload()  # no features

    result = run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )

    assert result.inserted == 0
    assert result.checkpoint_advanced_to == datetime(2014, 1, 2, tzinfo=timezone.utc)
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)


@patch(PATCH_TARGET)
def test_partially_rejected_batch_still_advances_checkpoint(mock_fetch, conn):
    valid_feature = make_feature("valid-1", 1000000000000)
    invalid_feature = {
        "id": "invalid-1",
        "properties": {"time": 1, "updated": 1, "mag": 1.0, "place": "X"},
        "geometry": {"coordinates": [-116.0, 999, 10.0]},  # bad latitude
    }
    mock_fetch.return_value = make_payload(valid_feature, invalid_feature)

    result = run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )

    assert result.inserted == 1
    assert result.rejected_count == 1
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)


@patch(PATCH_TARGET)
def test_rejected_records_are_persisted_and_checkpoint_advances(mock_fetch, conn):
    valid_feature = make_feature("valid-1", 1000000000000)
    invalid_feature = {
        "id": "invalid-1",
        "properties": {"time": 1, "updated": 1, "mag": 1.0, "place": "X"},
        "geometry": {"coordinates": [-116.0, 999, 10.0]},  # bad latitude
    }
    mock_fetch.return_value = make_payload(valid_feature, invalid_feature)

    result = run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )

    assert result.rejected_count == 1
    with conn.cursor() as cur:
        cur.execute("SELECT event_id FROM validation_failures")
        rows = cur.fetchall()
    assert rows == [("invalid-1",)]
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)


@patch("src.orchestration.usgs_pipeline.persist_rejected_records")
@patch(PATCH_TARGET)
def test_quarantine_failure_leaves_checkpoint_unchanged(mock_fetch, mock_persist, conn):
    from src.quarantine.validation_failures import QuarantineError

    mock_fetch.return_value = make_payload(make_feature("a", 1000000000000))
    mock_persist.side_effect = QuarantineError("simulated quarantine failure")

    with pytest.raises(QuarantineError):
        run_usgs_pipeline(
            conn, historical_start_time="2014-01-01", end_time="2014-01-02"
        )

    assert get_checkpoint(conn, "usgs") is None
    # valid record's load already committed -- unaffected by this failure
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM earthquakes WHERE event_id = %s", ("a",))
        assert cur.fetchone()[0] == 1


@patch(PATCH_TARGET)
def test_replaying_same_window_is_idempotent(mock_fetch, conn):
    mock_fetch.return_value = make_payload(make_feature("a", 1000000000000))

    first = run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )
    assert first.inserted == 1

    second = run_usgs_pipeline(
        conn, historical_start_time="2014-01-01", end_time="2014-01-02T00:00:00+00:00"
    )
    assert second.inserted == 0
    assert second.skipped == 1  # same updated value -> skipped, not duplicated

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM earthquakes WHERE event_id = %s", ("a",))
        assert cur.fetchone()[0] == 1
