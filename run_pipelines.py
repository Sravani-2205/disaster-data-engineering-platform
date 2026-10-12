import os
from datetime import datetime, timezone
import psycopg
from src.orchestration.pipeline_runner import run_all_pipelines

password = os.environ["POSTGRES_PASSWORD"]
year = datetime.now(timezone.utc).year

with psycopg.connect(f"dbname=disaster_data user=postgres password={password}") as conn:
    result = run_all_pipelines(conn, "2016-01-01", None, year)

for outcome in (result.usgs, result.noaa):
    status = "OK" if outcome.succeeded else f"FAILED: {outcome.error}"
    print(datetime.now(timezone.utc).isoformat(), outcome.source, status, outcome.result, flush=True)