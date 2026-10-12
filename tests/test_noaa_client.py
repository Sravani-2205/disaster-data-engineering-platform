"""
test_noaa_client.py

Tests for noaa_client.py. Never makes real HTTP calls -- requests.get
is mocked, matching the usgs_client.py test style exactly.
"""

import requests
import pytest
from datetime import date
from unittest.mock import patch, Mock

from src.ingestion.noaa_client import (
    list_storm_events_files,
    fetch_storm_events_year,
    NOAARequestError,
    NOAAResponseError,
)


SAMPLE_INDEX_HTML = """
<a href="StormEvents_details-ftp_v1.0_d2019_c20200219.csv.gz">StormEvents_details-ftp_v1.0_d2019_c20200219.csv.gz</a>
<a href="StormEvents_details-ftp_v1.0_d2020_c20260323.csv.gz">StormEvents_details-ftp_v1.0_d2020_c20260323.csv.gz</a>
<a href="StormEvents_fatalities-ftp_v1.0_d2019_c20200219.csv.gz">StormEvents_fatalities-ftp_v1.0_d2019_c20200219.csv.gz</a>
<a href="StormEvents_locations-ftp_v1.0_d2019_c20200219.csv.gz">StormEvents_locations-ftp_v1.0_d2019_c20200219.csv.gz</a>
"""


def _mock_get_response(text=None, content=None, status_ok=True):
    resp = Mock()
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    resp.text = text
    resp.content = content
    return resp


@patch("src.ingestion.noaa_client.requests.get")
def test_list_storm_events_files_parses_details_files_only(mock_get):
    mock_get.return_value = _mock_get_response(text=SAMPLE_INDEX_HTML)

    files = list_storm_events_files()

    assert files == {
        2019: ("StormEvents_details-ftp_v1.0_d2019_c20200219.csv.gz", date(2020, 2, 19)),
        2020: ("StormEvents_details-ftp_v1.0_d2020_c20260323.csv.gz", date(2026, 3, 23)),
    }
    # fatalities/locations files must NOT appear -- details files only


@patch("src.ingestion.noaa_client.requests.get")
def test_list_storm_events_files_keeps_latest_creation_date_per_year(mock_get):
    html = (
        '<a href="StormEvents_details-ftp_v1.0_d2019_c20190101.csv.gz">x</a>'
        '<a href="StormEvents_details-ftp_v1.0_d2019_c20200219.csv.gz">x</a>'
    )
    mock_get.return_value = _mock_get_response(text=html)

    files = list_storm_events_files()

    assert files[2019] == ("StormEvents_details-ftp_v1.0_d2019_c20200219.csv.gz", date(2020, 2, 19))


@patch("src.ingestion.noaa_client.requests.get")
def test_list_storm_events_files_raises_on_empty_listing(mock_get):
    mock_get.return_value = _mock_get_response(text="<html>no files here</html>")

    with pytest.raises(NOAAResponseError):
        list_storm_events_files()


@patch("src.ingestion.noaa_client.requests.get")
def test_list_storm_events_files_connection_error_raises_request_error(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("no network")

    with pytest.raises(NOAARequestError):
        list_storm_events_files()


@patch("src.ingestion.noaa_client.requests.get")
def test_list_storm_events_files_http_error_raises_request_error(mock_get):
    mock_get.return_value = _mock_get_response(text="", status_ok=False)

    with pytest.raises(NOAARequestError):
        list_storm_events_files()


@patch("src.ingestion.noaa_client.requests.get")
def test_fetch_storm_events_year_downloads_correct_file(mock_get):
    def side_effect(url, timeout):
        if url.endswith("csvfiles/"):
            return _mock_get_response(text=SAMPLE_INDEX_HTML)
        return _mock_get_response(content=b"fake gzip bytes")

    mock_get.side_effect = side_effect

    raw_bytes, creation_date = fetch_storm_events_year(2020)

    assert raw_bytes == b"fake gzip bytes"
    assert creation_date == date(2026, 3, 23)


@patch("src.ingestion.noaa_client.requests.get")
def test_fetch_storm_events_year_missing_year_raises_request_error(mock_get):
    mock_get.return_value = _mock_get_response(text=SAMPLE_INDEX_HTML)

    with pytest.raises(NOAARequestError):
        fetch_storm_events_year(1899)


@patch("src.ingestion.noaa_client.requests.get")
def test_fetch_storm_events_year_download_failure_raises_request_error(mock_get):
    def side_effect(url, timeout):
        if url.endswith("csvfiles/"):
            return _mock_get_response(text=SAMPLE_INDEX_HTML)
        raise requests.exceptions.Timeout("took too long")

    mock_get.side_effect = side_effect

    with pytest.raises(NOAARequestError):
        fetch_storm_events_year(2020)
