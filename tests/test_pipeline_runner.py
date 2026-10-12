"""
test_pipeline_runner.py

Integration tests for run_all_pipelines(). Only genuinely new
coverage is included here: cross-source coordination and failure
isolation between USGS and NOAA. Each source's own internal
semantics (load/quarantine/checkpoint behavior, idempotency) are
already covered in test_usgs_orchestration.py and
test_noaa_pipeline.py and are not re-tested here.

fetch_earthquake_data and NOAA's HTTP-facing calls are mocked; all
database interaction runs for real against disaster_data_test.
"""

import csv
import gzip
import io
import os
from datetime import date, datetime, timezone
from unittest.mock import patch

import psycopg
import pytest

from src.orchestration.pipeline_runner import run_all_pipelines
from src.checkpointing.usgs_checkpoint import get_checkpoint
from src.loading.usgs_loader import LoadError as USGSLoadError
from src.loading.noaa_loader import LoadError as NOAALoadError


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)

USGS_PATCH_TARGET = "src.orchestration.usgs_pipeline.fetch_earthquake_data"
NOAA_LISTING_PATCH_TARGET = "src.orchestration.noaa_pipeline.list_storm_events_files"
NOAA_FETCH_PATCH_TARGET = "src.ingestion.noaa_ingest.fetch_storm_events_year"

_NOAA_FIELDNAMES = [
    "EVENT_ID", "EPISODE_ID", "STATE", "EVENT_TYPE", "CZ_TYPE", "CZ_FIPS",
    "CZ_NAME", "BEGIN_DATE_TIME", "END_DATE_TIME", "CZ_TIMEZONE",
    "INJURIES_DIRECT", "INJURIES_INDIRECT", "DEATHS_DIRECT", "DEATHS_INDIRECT",
    "DAMAGE_PROPERTY", "DAMAGE_CROPS", "MAGNITUDE", "MAGNITUDE_TYPE",
    "TOR_F_SCALE", "BEGIN_LAT", "BEGIN_LON", "END_LAT", "END_LON",
]


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    with connection.cursor() as cur:
        cur.execute("TRUNCATE earthquakes;")
        cur.execute("TRUNCATE storm_events;")
        cur.execute("TRUNCATE ingestion_checkpoints;")
        cur.execute("TRUNCATE validation_failures;")
    connection.commit()

    yield connection

    connection.rollback()
    connection.close()


def make_usgs_feature(event_id, updated_millis, magnitude=1.0):
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


def make_usgs_payload(*features):
    return {"metadata": {"count": len(features)}, "features": list(features)}


def _noaa_valid_row(event_id: str) -> dict:
    row = {field: "" for field in _NOAA_FIELDNAMES}
    row.update(
        {
            "EVENT_ID": event_id,
            "STATE": "TEXAS",
            "EVENT_TYPE": "Tornado",
            "BEGIN_DATE_TIME": "01-JAN-19 00:00:00",
        }
    )
    return row


def _build_noaa_gzip_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_NOAA_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return gzip.compress(buf.getvalue().encode("utf-8"))


def _mock_noaa_listing(monkeypatch, year: int, creation: date):
    monkeypatch.setattr(
        NOAA_LISTING_PATCH_TARGET, lambda: {year: ("f.csv.gz", creation)}
    )


def _mock_noaa_fetch(monkeypatch, raw_bytes: bytes, creation: date):
    monkeypatch.setattr(
        NOAA_FETCH_PATCH_TARGET, lambda year, timeout=None: (raw_bytes, creation)
    )


@patch(USGS_PATCH_TARGET)
def test_both_sources_succeed_independently(mock_usgs_fetch, conn, monkeypatch):
    mock_usgs_fetch.return_value = make_usgs_payload(
        make_usgs_feature("eq-1", 1000000000000)
    )
    creation = date(2019, 2, 1)
    _mock_noaa_listing(monkeypatch, 2019, creation)
    _mock_noaa_fetch(monkeypatch, _build_noaa_gzip_csv([_noaa_valid_row("se-1")]), creation)

    result = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02T00:00:00+00:00",
        noaa_year=2019,
    )

    assert result.usgs.succeeded is True
    assert result.usgs.result.inserted == 1
    assert result.noaa.succeeded is True
    assert result.noaa.result.inserted == 1
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)
    assert get_checkpoint(conn, "noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)


@patch(USGS_PATCH_TARGET)
def test_usgs_failure_does_not_prevent_noaa_from_succeeding(
    mock_usgs_fetch, conn, monkeypatch
):
    from src.ingestion.usgs_client import USGSRequestError

    mock_usgs_fetch.side_effect = USGSRequestError("simulated USGS network failure")

    creation = date(2019, 2, 1)
    _mock_noaa_listing(monkeypatch, 2019, creation)
    _mock_noaa_fetch(monkeypatch, _build_noaa_gzip_csv([_noaa_valid_row("se-1")]), creation)

    result = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02",
        noaa_year=2019,
    )

    assert result.usgs.succeeded is False
    assert isinstance(result.usgs.error, USGSRequestError)
    assert get_checkpoint(conn, "usgs") is None

    assert result.noaa.succeeded is True
    assert result.noaa.result.inserted == 1
    assert get_checkpoint(conn, "noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)


@patch(USGS_PATCH_TARGET)
def test_noaa_failure_does_not_prevent_usgs_from_succeeding(
    mock_usgs_fetch, conn, monkeypatch
):
    mock_usgs_fetch.return_value = make_usgs_payload(
        make_usgs_feature("eq-1", 1000000000000)
    )

    def _raise_missing_year():
        return {}  # requested year never present -> handled as skip, not
        # a failure -- so instead force a genuine NOAA-side exception:

    # Force a real NOAA failure: listing itself fails.
    from src.ingestion.noaa_client import NOAAResponseError

    def _raise_response_error():
        raise NOAAResponseError("simulated NOAA listing parse failure")

    monkeypatch.setattr(NOAA_LISTING_PATCH_TARGET, _raise_response_error)

    result = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02T00:00:00+00:00",
        noaa_year=2019,
    )

    assert result.noaa.succeeded is False
    assert get_checkpoint(conn, "noaa") is None

    assert result.usgs.succeeded is True
    assert result.usgs.result.inserted == 1
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)


@patch("src.orchestration.usgs_pipeline.load_records")
@patch(USGS_PATCH_TARGET)
def test_combined_result_reports_partial_success_accurately(
    mock_usgs_fetch, mock_usgs_load, conn, monkeypatch
):
    mock_usgs_fetch.return_value = make_usgs_payload(
        make_usgs_feature("eq-1", 1000000000000)
    )
    mock_usgs_load.side_effect = USGSLoadError("simulated USGS load failure")

    creation = date(2019, 2, 1)
    _mock_noaa_listing(monkeypatch, 2019, creation)
    _mock_noaa_fetch(monkeypatch, _build_noaa_gzip_csv([_noaa_valid_row("se-1")]), creation)

    result = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02",
        noaa_year=2019,
    )

    assert result.usgs.succeeded is False
    assert result.usgs.result is None
    assert isinstance(result.usgs.error, USGSLoadError)

    assert result.noaa.succeeded is True
    assert result.noaa.error is None
    assert result.noaa.result.inserted == 1


@patch(USGS_PATCH_TARGET)
def test_retry_after_usgs_failure_preserves_idempotency(
    mock_usgs_fetch, conn, monkeypatch
):
    from src.ingestion.usgs_client import USGSRequestError

    creation = date(2019, 2, 1)
    _mock_noaa_listing(monkeypatch, 2019, creation)
    _mock_noaa_fetch(monkeypatch, _build_noaa_gzip_csv([_noaa_valid_row("se-1")]), creation)

    mock_usgs_fetch.side_effect = USGSRequestError("simulated failure")
    first = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02T00:00:00+00:00",
        noaa_year=2019,
    )
    assert first.usgs.succeeded is False
    assert get_checkpoint(conn, "usgs") is None

    mock_usgs_fetch.side_effect = None
    mock_usgs_fetch.return_value = make_usgs_payload(
        make_usgs_feature("eq-1", 1000000000000)
    )
    second = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02T00:00:00+00:00",
        noaa_year=2019,
    )

    assert second.usgs.succeeded is True
    assert second.usgs.result.inserted == 1
    assert get_checkpoint(conn, "usgs") == datetime(2014, 1, 2, tzinfo=timezone.utc)

    # NOAA already succeeded on the first combined call and shouldn't
    # be reprocessed/duplicated on retry (same revision -> true no-op).
    assert second.noaa.succeeded is True
    assert second.noaa.result.skipped_run is True
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM storm_events;")
        assert cur.fetchone()[0] == 1


@patch(USGS_PATCH_TARGET)
def test_both_sources_report_no_new_work(mock_usgs_fetch, conn, monkeypatch):
    mock_usgs_fetch.return_value = make_usgs_payload()  # no features
    creation = date(2019, 2, 1)
    _mock_noaa_listing(monkeypatch, 2019, creation)
    _mock_noaa_fetch(monkeypatch, _build_noaa_gzip_csv([_noaa_valid_row("se-1")]), creation)

    first = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-02T00:00:00+00:00",
        noaa_year=2019,
    )
    assert first.usgs.result.inserted == 0
    assert first.noaa.result.skipped_run is False

    # Second call: USGS still "processes" an empty batch (it has no
    # skip concept); NOAA sees the same revision and truly no-ops.
    second = run_all_pipelines(
        conn,
        usgs_historical_start_time="2014-01-01",
        usgs_end_time="2014-01-03T00:00:00+00:00",
        noaa_year=2019,
    )

    assert second.usgs.succeeded is True
    assert second.usgs.result.inserted == 0
    assert second.noaa.succeeded is True
    assert second.noaa.result.skipped_run is True
    assert get_checkpoint(conn, "noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)