"""
usgs_client.py

Responsibility: communicate with the USGS Earthquake Catalog API.

This module knows how to build a request and parse a response.
It does NOT know about files, ingestion workflow, or storage.
"""

import requests

from config.usgs_config import USGS_BASE_URL, DEFAULT_TIMEOUT_SECONDS


class USGSClientError(Exception):
    """Base exception for all usgs_client failures."""


class USGSRequestError(USGSClientError):
    """
    Raised when the HTTP request itself fails.

    Covers: network failures, timeouts, connection errors,
    and non-2xx HTTP status codes.
    """


class USGSResponseError(USGSClientError):
    """
    Raised when the HTTP request succeeded (2xx) but the response
    body could not be parsed as JSON.
    """


def fetch_earthquake_data(
    start_time: str,
    end_time: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    updated_after: str | None = None,
) -> dict:
    """
    Fetch earthquake data from the USGS Earthquake Catalog API
    for the given time window.

    Args:
        start_time: ISO date string, e.g. "2014-01-01". Maps to
            the API's `starttime` query parameter.
        end_time: ISO date string, e.g. "2014-01-02". Maps to
            the API's `endtime` query parameter.
        timeout: request timeout in seconds.
        updated_after: optional ISO date/time string. Maps to the
            API's `updatedafter` query parameter, which (per USGS's
            official documentation) limits results to events updated
            strictly after this time. Omitted from the request
            entirely when None (default), preserving prior behavior
            exactly.

    Returns:
        The parsed JSON response body as a dict. This function
        guarantees only that the HTTP request succeeded and that
        the body was valid JSON — it does not guarantee the JSON
        is shaped like a GeoJSON FeatureCollection. That structural
        check is a downstream responsibility.

    Raises:
        USGSRequestError: the request did not complete successfully
            (network failure, timeout, or non-2xx HTTP status).
        USGSResponseError: the request completed, but the response
            body could not be parsed as JSON.
    """
    params = {
        "format": "geojson",
        "starttime": start_time,
        "endtime": end_time,
    }
    if updated_after is not None:
        params["updatedafter"] = updated_after

    try:
        response = requests.get(USGS_BASE_URL, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        # Covers connection errors, timeouts, DNS failures, and
        # (via raise_for_status) non-2xx HTTP status codes.
        raise USGSRequestError(
            f"USGS request failed for window {start_time} to {end_time}: {exc}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise USGSResponseError(
            f"USGS response was not valid JSON for window "
            f"{start_time} to {end_time}: {exc}"
        ) from exc

    return payload
