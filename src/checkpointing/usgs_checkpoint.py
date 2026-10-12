"""
usgs_checkpoint.py

Responsibility: read and advance the ingestion checkpoint for a
source. The checkpoint represents the end_time of the most recent
ingestion window that was successfully fetched, staged, validated,
and loaded into PostgreSQL.

advance_checkpoint() must only be called after load_records() has
already succeeded. This module has no knowledge of the pipeline
sequence itself -- that orchestration is deliberately out of scope
for this milestone.
"""

from datetime import datetime, timezone

import psycopg


_SELECT_CHECKPOINT = """
    SELECT last_successful_run FROM ingestion_checkpoints
    WHERE source = %s;
"""

_UPSERT_CHECKPOINT = """
    INSERT INTO ingestion_checkpoints (source, last_successful_run, updated_at)
    VALUES (%s, %s, %s)
    ON CONFLICT (source) DO UPDATE SET
        last_successful_run = EXCLUDED.last_successful_run,
        updated_at = EXCLUDED.updated_at;
"""


def get_checkpoint(conn: psycopg.Connection, source: str = "usgs") -> datetime | None:
    """
    Return the stored last_successful_run for source, or None if no
    checkpoint row exists yet.
    """
    with conn.cursor() as cur:
        cur.execute(_SELECT_CHECKPOINT, (source,))
        row = cur.fetchone()

    return row[0] if row is not None else None


def advance_checkpoint(
    conn: psycopg.Connection,
    end_time: datetime,
    source: str = "usgs",
) -> None:
    """
    Advance (or create) the checkpoint for source to end_time.

    Call this only after the corresponding load_records() call has
    already committed successfully. Commits its own transaction.
    """
    updated_at = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute(_UPSERT_CHECKPOINT, (source, end_time, updated_at))

    conn.commit()
