"""
test_usgs_ingest.py

Tests for usgs_ingest.py. Mocks fetch_earthquake_data (no real HTTP).
Uses pytest's tmp_path fixture for file writes so tests never touch
the real data/raw/usgs/ directory.
"""

import json
import os
from unittest.mock import patch

import pytest

from src.ingestion.usgs_ingest import run_ingestion, IngestionResult, IngestionWriteError
from src.ingestion.usgs_client import USGSRequestError


SAMPLE_PAYLOAD = {
    "metadata": {"count": 2},
    "features": [{"id": "a"}, {"id": "b"}],
}

EMPTY_PAYLOAD = {"metadata": {"count": 0}, "features": []}


@patch("src.ingestion.usgs_ingest.fetch_earthquake_data")
def test_successful_ingestion_writes_file_and_returns_result(mock_fetch, tmp_path):
    mock_fetch.return_value = SAMPLE_PAYLOAD

    result = run_ingestion("2014-01-01", "2014-01-02", output_dir=str(tmp_path))

    assert isinstance(result, IngestionResult)
    assert result.feature_count == 2
    assert os.path.exists(result.raw_file_path)

    with open(result.raw_file_path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == SAMPLE_PAYLOAD


@patch("src.ingestion.usgs_ingest.fetch_earthquake_data")
def test_zero_features_is_successful_ingestion(mock_fetch, tmp_path):
    mock_fetch.return_value = EMPTY_PAYLOAD

    result = run_ingestion("2014-01-01", "2014-01-02", output_dir=str(tmp_path))

    assert result.feature_count == 0
    assert os.path.exists(result.raw_file_path)


@patch("src.ingestion.usgs_ingest.fetch_earthquake_data")
def test_client_error_propagates_and_no_file_written(mock_fetch, tmp_path):
    mock_fetch.side_effect = USGSRequestError("simulated failure")

    with pytest.raises(USGSRequestError):
        run_ingestion("2014-01-01", "2014-01-02", output_dir=str(tmp_path))

    assert os.listdir(tmp_path) == []


@patch("src.ingestion.usgs_ingest.open")
@patch("src.ingestion.usgs_ingest.fetch_earthquake_data")
def test_write_failure_raises_ingestion_write_error(mock_fetch, mock_open, tmp_path):
    mock_fetch.return_value = SAMPLE_PAYLOAD
    mock_open.side_effect = OSError("disk full")

    with pytest.raises(IngestionWriteError):
        run_ingestion("2014-01-01", "2014-01-02", output_dir=str(tmp_path))
