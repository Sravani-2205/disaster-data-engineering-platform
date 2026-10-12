"""
test_noaa_pipeline.py

Stage F integration tests against the real disaster_data_test
PostgreSQL database. Only external NOAA HTTP/network calls are
mocked -- list_storm_events_files() and the fetch call inside
run_noaa_ingestion() -- everything downstream (raw file write,
staging, validation, loading, quarantine, checkpoint) runs for real.
"""

import csv
import gzip
import io
import os
from datetime import date, datetime, timezone

import psycopg
import pytest

from src.checkpointing.usgs_checkpoint import get_checkpoint
from src.ingestion.noaa_client import NOAARequestError
from src.loading.noaa_loader import LoadError
from src.quarantine.validation_failures import QuarantineError
from src.orchestration.noaa_pipeline import run_noaa_pipeline


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)

_FIELDNAMES = [
    "EVENT_ID", "EPISODE_ID", "STATE", "EVENT_TYPE", "CZ_TYPE", "CZ_FIPS",
    "CZ_NAME", "BEGIN_DATE_TIME", "END_DATE_TIME", "CZ_TIMEZONE",
    "INJURIES_DIRECT", "INJURIES_INDIRECT", "DEATHS_DIRECT", "DEATHS_INDIRECT",
    "DAMAGE_PROPERTY", "DAMAGE_CROPS", "MAGNITUDE", "MAGNITUDE_TYPE",
    "TOR_F_SCALE", "BEGIN_LAT", "BEGIN_LON", "END_LAT", "END_LON",
]

_BLANK_ROW = {field: "" for field in _FIELDNAMES}


def _valid_row(event_id: str) -> dict:
    row = dict(_BLANK_ROW)
    row.update(
        {
            "EVENT_ID": event_id,
            "STATE": "TEXAS",
            "EVENT_TYPE": "Tornado",
            "BEGIN_DATE_TIME": "01-JAN-19 00:00:00",
        }
    )
    return row


def _invalid_row() -> dict:
    # Missing EVENT_ID -- required field -- triggers rejection.
    row = dict(_BLANK_ROW)
    row.update(
        {
            "STATE": "TEXAS",
            "EVENT_TYPE": "Hail",
            "BEGIN_DATE_TIME": "02-JAN-19 00:00:00",
        }
    )
    return row


def _build_gzip_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return gzip.compress(buf.getvalue().encode("utf-8"))


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)

    with connection.cursor() as cur:
        cur.execute("TRUNCATE storm_events;")
        cur.execute("TRUNCATE validation_failures;")
        cur.execute("TRUNCATE ingestion_checkpoints;")
    connection.commit()

    yield connection

    connection.rollback()
    connection.close()


def _mock_listing(monkeypatch, year: int, creation: date, filename: str = "f.csv.gz"):
    monkeypatch.setattr(
        "src.orchestration.noaa_pipeline.list_storm_events_files",
        lambda: {year: (filename, creation)},
    )


def _mock_fetch(monkeypatch, raw_bytes: bytes, creation: date):
    monkeypatch.setattr(
        "src.ingestion.noaa_ingest.fetch_storm_events_year",
        lambda year, timeout=None: (raw_bytes, creation),
    )


def _mock_empty_listing(monkeypatch):
    monkeypatch.setattr(
        "src.orchestration.noaa_pipeline.list_storm_events_files",
        lambda: {},
    )


def _storm_events_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM storm_events;")
        return cur.fetchone()[0]


def _validation_failures_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM validation_failures;")
        return cur.fetchone()[0]


def test_first_run_processes_and_advances_checkpoint(conn, monkeypatch, tmp_path):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001")])
    _mock_fetch(monkeypatch, raw, creation)

    result = run_noaa_pipeline(conn, year=2019)

    assert result.skipped_run is False
    assert result.inserted == 1
    assert result.updated == 0
    assert result.skipped == 0
    assert result.rejected_count == 0
    assert result.checkpoint_advanced_to == datetime(2019, 2, 1, tzinfo=timezone.utc)
    assert _storm_events_count(conn) == 1
    assert get_checkpoint(conn, source="noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)


def test_same_revision_is_true_noop(conn, monkeypatch):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001")])
    _mock_fetch(monkeypatch, raw, creation)

    first = run_noaa_pipeline(conn, year=2019)
    assert first.skipped_run is False

    second = run_noaa_pipeline(conn, year=2019)

    assert second.skipped_run is True
    assert second.inserted == 0
    assert second.updated == 0
    assert second.skipped == 0
    assert second.rejected_count == 0
    assert second.checkpoint_advanced_to is None
    # No new work at all -- storm_events count unchanged from first run.
    assert _storm_events_count(conn) == 1
    assert get_checkpoint(conn, source="noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)


def test_older_revision_is_noop(conn, monkeypatch):
    newer = date(2019, 3, 1)
    older = date(2019, 2, 1)

    _mock_listing(monkeypatch, 2019, newer)
    raw = _build_gzip_csv([_valid_row("1001")])
    _mock_fetch(monkeypatch, raw, newer)
    run_noaa_pipeline(conn, year=2019)

    _mock_listing(monkeypatch, 2019, older)

    result = run_noaa_pipeline(conn, year=2019)

    assert result.skipped_run is True
    assert result.checkpoint_advanced_to is None
    assert get_checkpoint(conn, source="noaa") == datetime(2019, 3, 1, tzinfo=timezone.utc)


def test_newer_revision_processes_and_advances(conn, monkeypatch):
    first_creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, first_creation)
    _mock_fetch(monkeypatch, _build_gzip_csv([_valid_row("1001")]), first_creation)
    run_noaa_pipeline(conn, year=2019)

    newer_creation = date(2019, 5, 1)
    _mock_listing(monkeypatch, 2019, newer_creation)
    _mock_fetch(monkeypatch, _build_gzip_csv([_valid_row("1001")]), newer_creation)

    result = run_noaa_pipeline(conn, year=2019)

    assert result.skipped_run is False
    assert result.checkpoint_advanced_to == datetime(2019, 5, 1, tzinfo=timezone.utc)
    assert get_checkpoint(conn, source="noaa") == datetime(2019, 5, 1, tzinfo=timezone.utc)


def test_missing_year_produces_skip_with_no_db_writes(conn, monkeypatch):
    _mock_listing(monkeypatch, 2020, date(2020, 1, 1))  # only 2020 published

    result = run_noaa_pipeline(conn, year=2019)  # requesting an unpublished year

    assert result.skipped_run is True
    assert result.source_file_creation_date is None
    assert result.inserted == 0
    assert result.updated == 0
    assert result.skipped == 0
    assert result.rejected_count == 0
    assert result.checkpoint_advanced_to is None
    assert _storm_events_count(conn) == 0
    assert _validation_failures_count(conn) == 0
    assert get_checkpoint(conn, source="noaa") is None


def test_invalid_records_load_and_quarantine_and_checkpoint_advances(conn, monkeypatch):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001"), _invalid_row()])
    _mock_fetch(monkeypatch, raw, creation)

    result = run_noaa_pipeline(conn, year=2019)

    assert result.skipped_run is False
    assert result.inserted == 1
    assert result.rejected_count == 1
    assert result.checkpoint_advanced_to == datetime(2019, 2, 1, tzinfo=timezone.utc)
    assert _storm_events_count(conn) == 1
    assert _validation_failures_count(conn) == 1
    assert get_checkpoint(conn, source="noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)


def test_load_failure_leaves_checkpoint_unchanged_and_skips_quarantine(
    conn, monkeypatch
):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001"), _invalid_row()])
    _mock_fetch(monkeypatch, raw, creation)

    def _raise_load_error(*args, **kwargs):
        raise LoadError("forced failure")

    monkeypatch.setattr(
        "src.orchestration.noaa_pipeline.load_records", _raise_load_error
    )

    persist_calls = []
    monkeypatch.setattr(
        "src.orchestration.noaa_pipeline.persist_rejected_records",
        lambda *a, **k: persist_calls.append(1) or 0,
    )

    with pytest.raises(LoadError):
        run_noaa_pipeline(conn, year=2019)

    assert persist_calls == []  # quarantine never reached
    assert get_checkpoint(conn, source="noaa") is None
    assert _storm_events_count(conn) == 0


def test_quarantine_failure_leaves_checkpoint_unchanged_valid_loads_remain(
    conn, monkeypatch
):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001"), _invalid_row()])
    _mock_fetch(monkeypatch, raw, creation)

    def _raise_quarantine_error(*args, **kwargs):
        raise QuarantineError("forced failure")

    monkeypatch.setattr(
        "src.orchestration.noaa_pipeline.persist_rejected_records",
        _raise_quarantine_error,
    )

    with pytest.raises(QuarantineError):
        run_noaa_pipeline(conn, year=2019)

    # load_records already committed its own transaction before
    # quarantine ran, so the valid record remains loaded.
    assert _storm_events_count(conn) == 1
    assert get_checkpoint(conn, source="noaa") is None
    assert _validation_failures_count(conn) == 0


def test_replay_after_success_same_revision_creates_no_duplicate_quarantine_rows(
    conn, monkeypatch
):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001"), _invalid_row()])
    _mock_fetch(monkeypatch, raw, creation)

    first = run_noaa_pipeline(conn, year=2019)
    assert first.rejected_count == 1
    assert _validation_failures_count(conn) == 1

    second = run_noaa_pipeline(conn, year=2019)

    assert second.skipped_run is True
    # True no-op: pipeline exits before staging/validation/quarantine
    # even run again, so no duplicate audit rows are created here.
    assert _validation_failures_count(conn) == 1


def test_crash_before_checkpoint_advance_reprocesses_and_allows_duplicate_quarantine(
    conn, monkeypatch
):
    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    raw = _build_gzip_csv([_valid_row("1001"), _invalid_row()])
    _mock_fetch(monkeypatch, raw, creation)

    from src.checkpointing.usgs_checkpoint import advance_checkpoint as real_advance

    calls: list[int] = []

    def _raise_advance_error_once(conn, end_time, source="noaa"):
        if not calls:
            calls.append(1)
            raise RuntimeError("simulated crash before checkpoint advance")
        return real_advance(conn, end_time, source=source)

    monkeypatch.setattr(
        "src.orchestration.noaa_pipeline.advance_checkpoint",
        _raise_advance_error_once,
    )

    with pytest.raises(RuntimeError):
        run_noaa_pipeline(conn, year=2019)

    # Quarantine already succeeded and committed before the simulated
    # crash, so its row is present even though checkpoint advancement
    # failed afterward.
    assert get_checkpoint(conn, source="noaa") is None
    assert _storm_events_count(conn) == 1
    assert _validation_failures_count(conn) == 1

    # Retry: checkpoint still unset, so this revision looks "new"
    # again and the pipeline correctly reprocesses.
    result = run_noaa_pipeline(conn, year=2019)

    assert result.skipped_run is False
    assert result.checkpoint_advanced_to == datetime(2019, 2, 1, tzinfo=timezone.utc)
    assert _storm_events_count(conn) == 1  # loader upsert: same revision -> skip, not duplicate
    # Quarantine ran again on retry: duplicate audit row is
    # intentional/accepted per the quarantine module's design.
    assert _validation_failures_count(conn) == 2


def test_noaa_checkpoint_does_not_affect_usgs_checkpoint(conn, monkeypatch):
    from src.checkpointing.usgs_checkpoint import advance_checkpoint

    usgs_time = datetime(2018, 1, 1, tzinfo=timezone.utc)
    advance_checkpoint(conn, usgs_time, source="usgs")

    creation = date(2019, 2, 1)
    _mock_listing(monkeypatch, 2019, creation)
    _mock_fetch(monkeypatch, _build_gzip_csv([_valid_row("1001")]), creation)

    run_noaa_pipeline(conn, year=2019)

    assert get_checkpoint(conn, source="usgs") == usgs_time
    assert get_checkpoint(conn, source="noaa") == datetime(2019, 2, 1, tzinfo=timezone.utc)