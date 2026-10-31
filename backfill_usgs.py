"""
backfill_usgs.py

One-off historical load of USGS earthquakes from START up to now.

USGS rejects any request that would return more than 20,000 events,
so the period is cut into half-month windows, and any window with
more than LIMIT events (counted first via the USGS count endpoint)
is split in half again until every piece fits.

The USGS checkpoint is cleared before each window, so every window
is fetched in full rather than filtered by `updatedafter`. Loads are
idempotent, so re-running this script never creates duplicates. When
it finishes, the checkpoint is left at `now`, ready for the normal
incremental runs of run_pipelines.py.
"""

import os
from datetime import datetime, timezone

import psycopg
import requests

from src.orchestration.usgs_pipeline import run_usgs_pipeline

START = datetime(2016, 1, 1)
LIMIT = 19000
COUNT_URL = "https://earthquake.usgs.gov/fdsnws/event/1/count"


def count(start, end):
    r = requests.get(
        COUNT_URL,
        params={"starttime": start.isoformat(), "endtime": end.isoformat()},
        timeout=60,
    )
    r.raise_for_status()
    return int(r.text)


def split(start, end):
    if count(start, end) <= LIMIT:
        return [(start, end)]
    mid = (start + (end - start) / 2).replace(microsecond=0)
    return split(start, mid) + split(mid, end)


def half_month_edges(start, end):
    """Window edges on the 1st and 16th of every month, from start to end."""
    edges = []
    d = start
    while d < end:
        edges.append(d)
        if d.day == 1:
            d = d.replace(day=16)
        elif d.month == 12:
            d = datetime(d.year + 1, 1, 1)
        else:
            d = datetime(d.year, d.month + 1, 1)
    edges.append(end)
    return edges


password = os.environ["POSTGRES_PASSWORD"]
now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
edges = half_month_edges(START, now)

with psycopg.connect(f"dbname=disaster_data user=postgres password={password}") as conn:
    for h_start, h_end in zip(edges, edges[1:]):
        for start, end in split(h_start, h_end):
            conn.execute("DELETE FROM ingestion_checkpoints WHERE source = 'usgs'")
            conn.commit()
            print(start, run_usgs_pipeline(conn, start.isoformat(), end.isoformat()), flush=True)
