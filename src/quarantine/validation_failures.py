"""
validation_failures.py

Responsibility: persist validation-rejected records into the
validation_failures table as a durable, append-only audit log.
No deduplication -- duplicate rows on window replay are intentional
(see Milestone 8 design). The original record is preserved exactly,
including None values, via psycopg's normal JSONB adaptation.
"""

import json
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from src.validation.usgs_validation import RejectedRecord


class QuarantineError(Exception):
    """Raised when a database error occurs while persisting rejected
    records. The transaction is rolled back before this is raised."""


_INSERT_REJECTED = """
    INSERT INTO validation_failures
        (source, event_id, record, reasons, rejected_at)
    VALUES
        (%s, %s, %s, %s, %s);
"""


def _json_default(obj):
    """
    Fallback serializer for values json.dumps cannot natively handle.

    Currently needed for Python `date` objects (e.g. NOAA's
    source_file_creation_date, parsed to a date in Stage C staging).
    Serializes any date/datetime-like object via .isoformat(), and
    falls back to str() for anything else unexpected. The original
    record passed in is never mutated -- this only affects how it is
    encoded to JSON for storage.
    """
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _to_jsonb(record: dict) -> Jsonb:
    """Wrap a record for JSONB storage, tolerating date/datetime values."""
    return Jsonb(record, dumps=lambda obj: json.dumps(obj, default=_json_default))


def persist_rejected_records(
    rejected_records: list[RejectedRecord],
    conn: psycopg.Connection,
    source: str = "usgs",
) -> int:
    """
    Persist rejected records into validation_failures.

    Every rejected record is inserted as its own row; no
    deduplication is performed. Empty input is a clean no-op
    returning 0. Commits its own transaction on success; on any
    database error the transaction is rolled back and QuarantineError
    is raised.
    """
    if not rejected_records:
        return 0

    rejected_at = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            for rejected in rejected_records:
                event_id = rejected.record.get("event_id")
                cur.execute(
                    _INSERT_REJECTED,
                    (
                        source,
                        event_id,
                        _to_jsonb(rejected.record),
                        rejected.reasons,
                        rejected_at,
                    ),
                )

        conn.commit()
    except psycopg.Error as exc:
        conn.rollback()
        raise QuarantineError(f"Failed to persist rejected records: {exc}") from exc

    return len(rejected_records)