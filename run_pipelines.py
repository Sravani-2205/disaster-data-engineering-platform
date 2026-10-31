import os
import sys
from datetime import datetime, timezone
import psycopg
from src.orchestration.pipeline_runner import run_all_pipelines

password = os.environ["POSTGRES_PASSWORD"]
year = datetime.now(timezone.utc).year

with psycopg.connect(f"dbname=disaster_data user=postgres password={password}") as conn:
    result = run_all_pipelines(conn, "2016-01-01", None, year)

outcomes = (result.usgs, result.noaa)

for outcome in outcomes:
    status = "OK" if outcome.succeeded else f"FAILED: {outcome.error}"
    print(datetime.now(timezone.utc).isoformat(), outcome.source, status, outcome.result, flush=True)

# Exit with a non-zero code if any source failed, so a scheduler or
# update_data.bat can tell a failed run from a successful one.
if not all(outcome.succeeded for outcome in outcomes):
    sys.exit(1)
