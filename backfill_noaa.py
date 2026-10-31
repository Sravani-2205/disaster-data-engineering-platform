import os
from datetime import datetime, timezone
import psycopg
from src.orchestration.noaa_pipeline import run_noaa_pipeline

password = os.environ["POSTGRES_PASSWORD"]
current_year = datetime.now(timezone.utc).year

with psycopg.connect(f"dbname=disaster_data user=postgres password={password}") as conn:
    for year in range(2016, current_year + 1):
        conn.execute("DELETE FROM ingestion_checkpoints WHERE source = 'noaa'")
        conn.commit()
        print(year, run_noaa_pipeline(conn, year), flush=True)