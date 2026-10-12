"""
noaa_ingest.py

Responsibility: orchestrate NOAA raw ingestion.
Calls noaa_client to obtain the gzip Event Details file for a
requested year, persists the raw gzip bytes to disk exactly as
received, and returns an IngestionResult. Does not decompress,
parse, stage, validate, load, checkpoint, or quarantine.
"""

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.ingestion.noaa_client import fetch_storm_events_year
from config.noaa_config import RAW_DATA_DIR, DEFAULT_TIMEOUT_SECONDS


class IngestionWriteError(Exception):
    """Raised when the raw gzip file could not be written to disk."""


@dataclass
class IngestionResult:
    raw_file_path: str
    byte_count: int
    year: int
    source_file_creation_date: date
    fetched_at: datetime


def run_noaa_ingestion(
    year: int,
    output_dir: str = RAW_DATA_DIR,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> IngestionResult:
    """
    Fetch the current NOAA Storm Events Details file for `year` and
    persist the raw gzip bytes to disk, unmodified.

    Raises:
        NOAARequestError, NOAAResponseError: propagated from
            noaa_client.
        IngestionWriteError: raw file could not be written.
    """
    raw_bytes, creation_date = fetch_storm_events_year(year, timeout=timeout)

    fetched_at = datetime.now(timezone.utc)
    timestamp_str = fetched_at.strftime("%Y%m%dT%H%M%S%fZ")
    creation_str = creation_date.strftime("%Y%m%d")

    filename = (
        f"StormEvents_details_d{year}_c{creation_str}"
        f"_fetched_{timestamp_str}.csv.gz"
    )
    file_path = os.path.join(output_dir, filename)

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(raw_bytes)
    except OSError as exc:
        raise IngestionWriteError(
            f"Failed to write raw NOAA ingestion file to {file_path}: {exc}"
        ) from exc

    return IngestionResult(
        raw_file_path=file_path,
        byte_count=len(raw_bytes),
        year=year,
        source_file_creation_date=creation_date,
        fetched_at=fetched_at,
    )
