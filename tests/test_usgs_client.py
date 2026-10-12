"""
test_usgs_client.py

Tests for usgs_client.py.

These tests never make a real HTTP call. `requests.get` is replaced
("mocked") with a fake version we control, so we can force each
failure mode on demand and check that fetch_earthquake_data reacts
correctly.
"""

import requests
import pytest
from unittest.mock import patch, Mock

from src.ingestion.usgs_client import (
    fetch_earthquake_data,
    USGSRequestError,
    USGSResponseError,
)
from config.usgs_config import USGS_BASE_URL, DEFAULT_TIMEOUT_SECONDS


@patch("src.ingestion.usgs_client.requests.get")
def test_successful_response_returns_parsed_json(mock_get):
    """
    If the HTTP call succeeds and the body is valid JSON,
    fetch_earthquake_data should return that JSON unchanged.
    """
    fake_payload = {"metadata": {"count": 1}, "features": [{"id": "abc"}]}

    fake_response = Mock()
    fake_response.raise_for_status.return_value = None  # no error
    fake_response.json.return_value = fake_payload
    mock_get.return_value = fake_response

    result = fetch_earthquake_data("2014-01-01", "2014-01-02")

    assert result == fake_payload

    # Also verify *how* the request was constructed, not just what
    # came back. This catches bugs like a typo'd param name or a
    # missing timeout that the previous assertion alone would miss.
    mock_get.assert_called_once_with(
        USGS_BASE_URL,
        params={
            "format": "geojson",
            "starttime": "2014-01-01",
            "endtime": "2014-01-02",
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


@patch("src.ingestion.usgs_client.requests.get")
def test_connection_error_raises_usgs_request_error(mock_get):
    """
    If requests.get cannot connect at all (e.g. no network),
    that should be wrapped as our own USGSRequestError, not
    leak out as a raw requests exception.
    """
    mock_get.side_effect = requests.exceptions.ConnectionError("no network")

    with pytest.raises(USGSRequestError):
        fetch_earthquake_data("2014-01-01", "2014-01-02")


@patch("src.ingestion.usgs_client.requests.get")
def test_timeout_raises_usgs_request_error(mock_get):
    """
    If the request takes too long and times out, that should
    also be wrapped as USGSRequestError.
    """
    mock_get.side_effect = requests.exceptions.Timeout("took too long")

    with pytest.raises(USGSRequestError):
        fetch_earthquake_data("2014-01-01", "2014-01-02")


@patch("src.ingestion.usgs_client.requests.get")
def test_http_error_status_raises_usgs_request_error(mock_get):
    """
    If USGS responds but with a bad status code (e.g. 500),
    raise_for_status() raises requests.exceptions.HTTPError.
    That should be wrapped as USGSRequestError, same as a
    connection failure -- from the caller's point of view,
    both mean "the request did not succeed."
    """
    fake_response = Mock()
    fake_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "500 Server Error"
    )
    mock_get.return_value = fake_response

    with pytest.raises(USGSRequestError):
        fetch_earthquake_data("2014-01-01", "2014-01-02")


@patch("src.ingestion.usgs_client.requests.get")
def test_invalid_json_raises_usgs_response_error(mock_get):
    """
    If the HTTP call succeeds (2xx) but the response body is not
    valid JSON, response.json() raises ValueError. That should be
    wrapped as USGSResponseError -- a different exception type
    than request failures, because the request itself succeeded;
    only the body was unusable.
    """
    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.side_effect = ValueError("not valid json")
    mock_get.return_value = fake_response

    with pytest.raises(USGSResponseError):
        fetch_earthquake_data("2014-01-01", "2014-01-02")


@patch("src.ingestion.usgs_client.requests.get")
def test_updated_after_none_is_omitted_from_params(mock_get):
    """
    Regression test: when updated_after is not supplied (the
    default), the request params must be identical to prior
    behavior -- no 'updatedafter' key at all.
    """
    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"features": []}
    mock_get.return_value = fake_response

    fetch_earthquake_data("2014-01-01", "2014-01-02")

    mock_get.assert_called_once_with(
        USGS_BASE_URL,
        params={
            "format": "geojson",
            "starttime": "2014-01-01",
            "endtime": "2014-01-02",
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


@patch("src.ingestion.usgs_client.requests.get")
def test_updated_after_included_when_provided(mock_get):
    """
    When updated_after is supplied, it must be included in the
    request params as 'updatedafter'.
    """
    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"features": []}
    mock_get.return_value = fake_response

    fetch_earthquake_data(
        "2014-01-01", "2014-01-02", updated_after="2014-01-01T00:00:00+00:00"
    )

    mock_get.assert_called_once_with(
        USGS_BASE_URL,
        params={
            "format": "geojson",
            "starttime": "2014-01-01",
            "endtime": "2014-01-02",
            "updatedafter": "2014-01-01T00:00:00+00:00",
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
