"""
usgs_ingest.py

Responsibility: orchestrate USGS ingestion.
Calls usgs_client, persists the raw response to disk, returns an
IngestionResult. Does not validate, transform, or load to a database.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from src.ingestion.usgs_client import fetch_earthquake_data
from config.usgs_config import RAW_DATA_DIR, DEFAULT_TIMEOUT_SECONDS


class IngestionWriteError(Exception):
    """Raised when the raw response could not be written to disk."""


@dataclass
class IngestionResult:
    raw_file_path: str
    feature_count: int
    fetched_at: datetime


def run_ingestion(
    start_time: str,
    end_time: str,
    output_dir: str = RAW_DATA_DIR,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> IngestionResult:
    """
    Fetch USGS earthquake data for the given window and persist the
    raw response to disk.

    Raises:
        USGSRequestError, USGSResponseError: propagated from usgs_client.
        IngestionWriteError: raw file could not be written.
    """
    payload = fetch_earthquake_data(start_time, end_time, timeout=timeout)

    fetched_at = datetime.now(timezone.utc)
    feature_count = len(payload.get("features", []))

    timestamp_str = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    filename = f"usgs_{start_time}_{end_time}_{timestamp_str}.json"
    file_path = os.path.join(output_dir, filename)

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError as exc:
        raise IngestionWriteError(
            f"Failed to write raw ingestion file to {file_path}: {exc}"
        ) from exc

    return IngestionResult(
        raw_file_path=file_path,
        feature_count=feature_count,
        fetched_at=fetched_at,
    )
