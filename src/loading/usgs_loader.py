"""
usgs_loader.py

Responsibility: load validated USGS records into the PostgreSQL
`earthquakes` table using an atomic, idempotent upsert strategy.

Insert/update/skip classification is determined via an explicit
SELECT-then-act check (not PostgreSQL's xmax system column), inside
one transaction per load_records() call.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg


class LoadError(Exception):
    """Raised when a database error occurs during loading. The
    transaction is rolled back before this is raised."""


@dataclass
class LoadResult:
    inserted: int
    updated: int
    skipped: int


_SELECT_EXISTING = """
    SELECT updated FROM earthquakes
    WHERE source = %s AND event_id = %s;
"""

_INSERT = """
    INSERT INTO earthquakes
        (source, event_id, time, updated, magnitude, place, latitude, longitude, depth, ingested_at)
    VALUES
        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

_UPDATE = """
    UPDATE earthquakes
    SET
        time = %s,
        updated = %s,
        magnitude = %s,
        place = %s,
        latitude = %s,
        longitude = %s,
        depth = %s,
        ingested_at = %s
    WHERE source = %s
      AND event_id = %s
      AND updated < %s;
"""


def _epoch_millis_to_datetime(epoch_millis) -> datetime:
    return datetime.fromtimestamp(epoch_millis / 1000, tz=timezone.utc)


def load_records(
    valid_records: list[dict],
    conn: psycopg.Connection,
    source: str = "usgs",
) -> LoadResult:
    """
    Load validated records into the earthquakes table.

    One transaction covers the whole call: on any database error,
    the transaction is rolled back and LoadError is raised. Nothing
    is partially committed.
    """
    inserted = 0
    updated = 0
    skipped = 0

    ingested_at = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            for record in valid_records:
                event_id = record["event_id"]
                incoming_time = _epoch_millis_to_datetime(record["time"])
                incoming_updated = _epoch_millis_to_datetime(record["updated"])
                magnitude = record.get("magnitude")
                place = record.get("place")
                latitude = record["latitude"]
                longitude = record["longitude"]
                depth = record.get("depth")

                cur.execute(_SELECT_EXISTING, (source, event_id))
                row = cur.fetchone()

                if row is None:
                    cur.execute(
                        _INSERT,
                        (
                            source,
                            event_id,
                            incoming_time,
                            incoming_updated,
                            magnitude,
                            place,
                            latitude,
                            longitude,
                            depth,
                            ingested_at,
                        ),
                    )
                    inserted += 1
                else:
                    stored_updated = row[0]
                    if incoming_updated > stored_updated:
                        cur.execute(
                            _UPDATE,
                            (
                                incoming_time,
                                incoming_updated,
                                magnitude,
                                place,
                                latitude,
                                longitude,
                                depth,
                                ingested_at,
                                source,
                                event_id,
                                incoming_updated,
                            ),
                        )
                        updated += 1
                    else:
                        skipped += 1

        conn.commit()
    except psycopg.Error as exc:
        conn.rollback()
        raise LoadError(f"Failed to load records: {exc}") from exc

    return LoadResult(inserted=inserted, updated=updated, skipped=skipped)
