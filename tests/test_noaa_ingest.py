"""
test_noaa_ingest.py

Tests for noaa_ingest.py. Mocks fetch_storm_events_year (no real
HTTP). Uses pytest's tmp_path fixture for file writes so tests never
touch the real data/raw/noaa/ directory.
"""

import os
from datetime import date
from unittest.mock import patch

import pytest

from src.ingestion.noaa_ingest import (
    run_noaa_ingestion,
    IngestionResult,
    IngestionWriteError,
)
from src.ingestion.noaa_client import NOAARequestError, NOAAResponseError


SAMPLE_BYTES = b"\x1f\x8b\x08fake-gzip-bytes-not-real-but-opaque"
SAMPLE_CREATION_DATE = date(2020, 2, 19)


@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_successful_ingestion_writes_file_and_returns_result(mock_fetch, tmp_path):
    mock_fetch.return_value = (SAMPLE_BYTES, SAMPLE_CREATION_DATE)

    result = run_noaa_ingestion(2019, output_dir=str(tmp_path))

    assert isinstance(result, IngestionResult)
    assert result.year == 2019
    assert result.source_file_creation_date == SAMPLE_CREATION_DATE
    assert result.byte_count == len(SAMPLE_BYTES)
    assert os.path.exists(result.raw_file_path)

    with open(result.raw_file_path, "rb") as f:
        saved = f.read()
    assert saved == SAMPLE_BYTES


@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_saved_bytes_are_exactly_client_bytes_unmodified(mock_fetch, tmp_path):
    # Deliberately not valid gzip -- proves no decompression/parsing occurs.
    opaque_bytes = b"not-actually-gzip-just-opaque-bytes"
    mock_fetch.return_value = (opaque_bytes, SAMPLE_CREATION_DATE)

    result = run_noaa_ingestion(2019, output_dir=str(tmp_path))

    with open(result.raw_file_path, "rb") as f:
        saved = f.read()
    assert saved == opaque_bytes


@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_client_request_error_propagates_and_no_file_written(mock_fetch, tmp_path):
    mock_fetch.side_effect = NOAARequestError("simulated failure")

    with pytest.raises(NOAARequestError):
        run_noaa_ingestion(2019, output_dir=str(tmp_path))

    assert os.listdir(tmp_path) == []


@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_client_response_error_propagates_and_no_file_written(mock_fetch, tmp_path):
    mock_fetch.side_effect = NOAAResponseError("simulated failure")

    with pytest.raises(NOAAResponseError):
        run_noaa_ingestion(2019, output_dir=str(tmp_path))

    assert os.listdir(tmp_path) == []


@patch("src.ingestion.noaa_ingest.open")
@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_write_failure_raises_ingestion_write_error(mock_fetch, mock_open, tmp_path):
    mock_fetch.return_value = (SAMPLE_BYTES, SAMPLE_CREATION_DATE)
    mock_open.side_effect = OSError("disk full")

    with pytest.raises(IngestionWriteError):
        run_noaa_ingestion(2019, output_dir=str(tmp_path))


@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_filename_contains_year_and_creation_date(mock_fetch, tmp_path):
    mock_fetch.return_value = (SAMPLE_BYTES, SAMPLE_CREATION_DATE)

    result = run_noaa_ingestion(2019, output_dir=str(tmp_path))
    filename = os.path.basename(result.raw_file_path)

    assert "2019" in filename
    assert "20200219" in filename


@patch("src.ingestion.noaa_ingest.fetch_storm_events_year")
def test_repeated_captures_do_not_overwrite_previous_raw_files(mock_fetch, tmp_path):
    mock_fetch.return_value = (SAMPLE_BYTES, SAMPLE_CREATION_DATE)

    first = run_noaa_ingestion(2019, output_dir=str(tmp_path))
    second = run_noaa_ingestion(2019, output_dir=str(tmp_path))

    assert first.raw_file_path != second.raw_file_path
    assert os.path.exists(first.raw_file_path)
    assert os.path.exists(second.raw_file_path)
    assert len(os.listdir(tmp_path)) == 2
