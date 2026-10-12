"""
noaa_loader.py

Responsibility: load validated NOAA Storm Events records into the
PostgreSQL `storm_events` table using an atomic, idempotent upsert
strategy.

Unlike USGS (which uses a per-record `updated` timestamp), NOAA has
no per-record revision signal. Insert/update/skip classification is
therefore based entirely on `source_file_creation_date` -- a
file-level revision marker -- via an explicit SELECT-then-act check
(not PostgreSQL's xmax system column), inside one transaction per
load_records() call.

Equal source_file_creation_date always means SKIP, regardless of
whether any other field differs; there is no field-level diffing.

This module does not validate, transform, or reject records -- it
assumes valid_records has already passed Stage D validation.
Damage and datetime fields are loaded as raw strings, unchanged.
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
    SELECT source_file_creation_date FROM storm_events
    WHERE source = %s AND event_id = %s;
"""

_INSERT = """
    INSERT INTO storm_events
        (source, event_id, episode_id, state, event_type, cz_type, cz_fips,
         cz_name, begin_date_time, end_date_time, cz_timezone,
         injuries_direct, injuries_indirect, deaths_direct, deaths_indirect,
         damage_property, damage_crops, magnitude, magnitude_type,
         tor_f_scale, begin_lat, begin_lon, end_lat, end_lon,
         source_file_year, source_file_creation_date, ingested_at)
    VALUES
        (%s, %s, %s, %s, %s, %s, %s,
         %s, %s, %s, %s,
         %s, %s, %s, %s,
         %s, %s, %s, %s,
         %s, %s, %s, %s, %s,
         %s, %s, %s);
"""

_UPDATE = """
    UPDATE storm_events
    SET
        episode_id = %s,
        state = %s,
        event_type = %s,
        cz_type = %s,
        cz_fips = %s,
        cz_name = %s,
        begin_date_time = %s,
        end_date_time = %s,
        cz_timezone = %s,
        injuries_direct = %s,
        injuries_indirect = %s,
        deaths_direct = %s,
        deaths_indirect = %s,
        damage_property = %s,
        damage_crops = %s,
        magnitude = %s,
        magnitude_type = %s,
        tor_f_scale = %s,
        begin_lat = %s,
        begin_lon = %s,
        end_lat = %s,
        end_lon = %s,
        source_file_year = %s,
        source_file_creation_date = %s,
        ingested_at = %s
    WHERE source = %s
      AND event_id = %s
      AND source_file_creation_date < %s;
"""


def load_records(
    valid_records: list[dict],
    conn: psycopg.Connection,
    source: str = "noaa",
) -> LoadResult:
    """
    Load validated NOAA records into the storm_events table.

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
                incoming_creation_date = record["source_file_creation_date"]

                cur.execute(_SELECT_EXISTING, (source, event_id))
                row = cur.fetchone()

                data_fields = (
                    record.get("episode_id"),
                    record["state"],
                    record["event_type"],
                    record.get("cz_type"),
                    record.get("cz_fips"),
                    record.get("cz_name"),
                    record["begin_date_time"],
                    record.get("end_date_time"),
                    record.get("cz_timezone"),
                    record.get("injuries_direct"),
                    record.get("injuries_indirect"),
                    record.get("deaths_direct"),
                    record.get("deaths_indirect"),
                    record.get("damage_property"),
                    record.get("damage_crops"),
                    record.get("magnitude"),
                    record.get("magnitude_type"),
                    record.get("tor_f_scale"),
                    record.get("begin_lat"),
                    record.get("begin_lon"),
                    record.get("end_lat"),
                    record.get("end_lon"),
                    record["source_file_year"],
                    incoming_creation_date,
                )

                if row is None:
                    cur.execute(
                        _INSERT,
                        (source, event_id) + data_fields + (ingested_at,),
                    )
                    inserted += 1
                else:
                    stored_creation_date = row[0]
                    if incoming_creation_date > stored_creation_date:
                        cur.execute(
                            _UPDATE,
                            data_fields
                            + (ingested_at, source, event_id, incoming_creation_date),
                        )
                        updated += 1
                    else:
                        skipped += 1

        conn.commit()
    except psycopg.Error as exc:
        conn.rollback()
        raise LoadError(f"Failed to load records: {exc}") from exc

    return LoadResult(inserted=inserted, updated=updated, skipped=skipped)
