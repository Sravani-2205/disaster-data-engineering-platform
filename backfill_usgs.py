import os
from datetime import datetime, timezone
import psycopg
import requests
from src.orchestration.usgs_pipeline import run_usgs_pipeline

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


password = os.environ["POSTGRES_PASSWORD"]
now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

edges = []
for m in range(1, 10):
    edges += [datetime(2026, m, 1), datetime(2026, m, 16)]
edges += [datetime(2026, 10, 1), now]

with psycopg.connect(f"dbname=disaster_data user=postgres password={password}") as conn:
    for h_start, h_end in zip(edges, edges[1:]):
        for start, end in split(h_start, h_end):
            print(start, run_usgs_pipeline(conn, start.isoformat(), end.isoformat()), flush=True)