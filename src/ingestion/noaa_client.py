"""
noaa_client.py

Responsibility: communicate with NCEI's Storm Events bulk CSV
distribution. Unlike USGS, there is no queryable JSON API -- NCEI
publishes one gzip CSV per year, with the file's creation date
embedded in its filename. This module resolves which file currently
represents a given year and downloads it.

This module does NOT parse CSV content, write files, or perform any
ingestion orchestration -- same client/ingestion split as the USGS
pipeline.
"""

import re
from datetime import date

import requests

from config.noaa_config import NOAA_CSVFILES_INDEX_URL, DEFAULT_TIMEOUT_SECONDS


class NOAAClientError(Exception):
    """Base exception for all noaa_client failures."""


class NOAARequestError(NOAAClientError):
    """
    Raised when an HTTP request (the directory listing or a file
    download) fails: network failures, timeouts, connection errors,
    or non-2xx HTTP status codes. Also raised when a requested year
    has no published Event Details file.
    """


class NOAAResponseError(NOAAClientError):
    """
    Raised when a request succeeded but the response body could not
    be used: the directory listing page could not be parsed for any
    Event Details filenames at all.
    """


# Matches: StormEvents_details-ftp_v1.0_d2019_c20200219.csv.gz
_DETAILS_FILENAME_PATTERN = re.compile(
    r"StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz"
)


def list_storm_events_files(timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[int, tuple[str, date]]:
    """
    Fetch and parse the NCEI Storm Events csvfiles directory index,
    returning Event Details files only.

    Returns:
        {year: (filename, creation_date)} -- one entry per year
        currently published. If NCEI ever lists more than one
        creation date for the same year (not observed in practice --
        NCEI replaces rather than accumulates), the file with the
        latest creation date wins.

    Raises:
        NOAARequestError: the directory listing request failed.
        NOAAResponseError: the directory listing succeeded but no
            Event Details filenames could be found in it at all.
    """
    try:
        response = requests.get(NOAA_CSVFILES_INDEX_URL, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise NOAARequestError(
            f"Failed to fetch NOAA Storm Events directory listing: {exc}"
        ) from exc

    matches = _DETAILS_FILENAME_PATTERN.findall(response.text)
    if not matches:
        raise NOAAResponseError(
            "No Storm Events Details filenames found in the NCEI directory listing."
        )

    files: dict[int, tuple[str, date]] = {}
    for year_str, creation_str in matches:
        year = int(year_str)
        creation_date = date(
            int(creation_str[0:4]), int(creation_str[4:6]), int(creation_str[6:8])
        )
        filename = f"StormEvents_details-ftp_v1.0_d{year_str}_c{creation_str}.csv.gz"

        existing = files.get(year)
        if existing is None or creation_date > existing[1]:
            files[year] = (filename, creation_date)

    return files


def fetch_storm_events_year(
    year: int, timeout: int = DEFAULT_TIMEOUT_SECONDS
) -> tuple[bytes, date]:
    """
    Resolve the current Event Details file for `year` and download it.

    Returns:
        (raw_gzip_bytes, creation_date)

    Raises:
        NOAARequestError: `year` has no published file, or the
            download request failed.
        NOAAResponseError: propagated from list_storm_events_files
            if the directory listing itself could not be parsed.
    """
    available_files = list_storm_events_files(timeout=timeout)

    if year not in available_files:
        raise NOAARequestError(
            f"No NOAA Storm Events Details file is published for year {year}."
        )

    filename, creation_date = available_files[year]
    file_url = NOAA_CSVFILES_INDEX_URL + filename

    try:
        response = requests.get(file_url, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise NOAARequestError(
            f"Failed to download NOAA Storm Events file for year {year}: {exc}"
        ) from exc

    return response.content, creation_date
