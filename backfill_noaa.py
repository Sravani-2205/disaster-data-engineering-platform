import os
import psycopg
from src.orchestration.noaa_pipeline import run_noaa_pipeline

password = os.environ["POSTGRES_PASSWORD"]

with psycopg.connect(f"dbname=disaster_data user=postgres password={password}") as conn:
    for year in range(2016, 2026):
        if year == 2020:
            continue
        conn.execute("DELETE FROM ingestion_checkpoints WHERE source = 'noaa'")
        conn.commit()
        print(year, run_noaa_pipeline(conn, year), flush=True)