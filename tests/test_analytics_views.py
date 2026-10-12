"""
test_analytics_views.py

Deterministic correctness tests for the Milestone 11 analytical
views, against disaster_data_test. Fixture rows are inserted
directly into earthquakes/storm_events (bypassing the pipeline,
since these tests are about view SQL correctness, not ingestion)
and the views are queried and asserted against by hand-computed
expected values.
"""

import os
from datetime import datetime, timezone

import psycopg
import pytest


TEST_DB_DSN = (
    f"dbname=disaster_data_test user=postgres "
    f"password={os.environ['POSTGRES_PASSWORD']}"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(TEST_DB_DSN)
    with connection.cursor() as cur:
        cur.execute("TRUNCATE earthquakes;")
        cur.execute("TRUNCATE storm_events;")
    connection.commit()
    yield connection
    connection.rollback()
    connection.close()


def insert_earthquake(conn, event_id, time_, magnitude, depth=10.0, lat=33.0, lon=-116.0):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO earthquakes
                (source, event_id, time, updated, magnitude, place,
                 latitude, longitude, depth, ingested_at)
            VALUES ('usgs', %s, %s, %s, %s, 'Somewhere', %s, %s, %s, %s)
            """,
            (event_id, time_, time_, magnitude, lat, lon, depth, datetime.now(timezone.utc)),
        )
    conn.commit()


def insert_storm_event(
    conn,
    event_id,
    state,
    event_type,
    begin_date_time,
    injuries_direct=None,
    injuries_indirect=None,
    deaths_direct=None,
    deaths_indirect=None,
    damage_property=None,
    damage_crops=None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO storm_events
                (source, event_id, state, event_type, begin_date_time,
                 injuries_direct, injuries_indirect, deaths_direct, deaths_indirect,
                 damage_property, damage_crops,
                 source_file_year, source_file_creation_date, ingested_at)
            VALUES ('noaa', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2019, '2019-01-01', %s)
            """,
            (
                event_id, state, event_type, begin_date_time,
                injuries_direct, injuries_indirect, deaths_direct, deaths_indirect,
                damage_property, damage_crops,
                datetime.now(timezone.utc),
            ),
        )
    conn.commit()


def fetch_all(conn, query):
    with conn.cursor() as cur:
        cur.execute(query)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------- earthquakes ----------

def test_earthquake_significant_flag_uses_defined_threshold(conn):
    insert_earthquake(conn, "eq-low", datetime(2020, 1, 1, tzinfo=timezone.utc), magnitude=5.9)
    insert_earthquake(conn, "eq-high", datetime(2020, 1, 1, tzinfo=timezone.utc), magnitude=6.0)

    rows = fetch_all(
        conn, "SELECT event_id, is_significant FROM vw_earthquakes_enriched ORDER BY event_id"
    )
    result = {r["event_id"]: r["is_significant"] for r in rows}
    assert result["eq-low"] is False
    assert result["eq-high"] is True


def test_earthquake_null_magnitude_is_not_significant_and_preserved_as_null(conn):
    insert_earthquake(conn, "eq-null", datetime(2020, 1, 1, tzinfo=timezone.utc), magnitude=None)

    rows = fetch_all(conn, "SELECT magnitude, is_significant FROM vw_earthquakes_enriched")
    assert rows[0]["magnitude"] is None
    assert rows[0]["is_significant"] is False


def test_earthquake_daily_summary_counts_and_avg_magnitude_correct(conn):
    day = datetime(2020, 3, 5, 1, 0, tzinfo=timezone.utc)
    insert_earthquake(conn, "eq-1", day, magnitude=4.0)
    insert_earthquake(conn, "eq-2", day.replace(hour=3), magnitude=6.0)

    rows = fetch_all(conn, "SELECT * FROM vw_earthquake_daily_summary")
    assert len(rows) == 1  # both events close together in UTC -> one grouped row
    assert rows[0]["event_count"] == 2
    assert rows[0]["significant_count"] == 1
    assert rows[0]["avg_magnitude"] == pytest.approx(5.0)

def test_earthquake_daily_summary_groups_separate_days_independently(conn):
    insert_earthquake(conn, "eq-1", datetime(2020, 1, 1, tzinfo=timezone.utc), magnitude=4.0)
    insert_earthquake(conn, "eq-2", datetime(2020, 1, 2, tzinfo=timezone.utc), magnitude=4.0)

    rows = fetch_all(conn, "SELECT event_count FROM vw_earthquake_daily_summary")
    assert len(rows) == 2
    assert all(r["event_count"] == 1 for r in rows)


# ---------- storm events ----------

def test_storm_begin_timestamp_parses_valid_format(conn):
    insert_storm_event(conn, "se-1", "TEXAS", "Tornado", "01-JAN-19 00:00:00")

    rows = fetch_all(conn, "SELECT begin_timestamp FROM vw_storm_events_enriched")
    parsed = rows[0]["begin_timestamp"]
    # begin_timestamp is anchored to UTC by fixed convention in the
    # view (AT TIME ZONE 'UTC'), independent of session timezone --
    # so the literal wall-clock string should map directly to the
    # same UTC instant regardless of where this test runs.
    assert parsed.astimezone(timezone.utc) == datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

def test_storm_begin_timestamp_malformed_yields_null_not_error(conn):
    insert_storm_event(conn, "se-bad", "TEXAS", "Tornado", "not-a-date")

    rows = fetch_all(conn, "SELECT begin_timestamp FROM vw_storm_events_enriched")
    assert rows[0]["begin_timestamp"] is None


def test_storm_damage_property_parses_k_m_b_suffixes(conn):
    insert_storm_event(conn, "se-k", "TX", "Hail", "01-JAN-19 00:00:00", damage_property="10.00K")
    insert_storm_event(conn, "se-m", "TX", "Hail", "01-JAN-19 00:00:00", damage_property="2.50M")
    insert_storm_event(conn, "se-b", "TX", "Hail", "01-JAN-19 00:00:00", damage_property="1.00B")

    rows = fetch_all(
        conn, "SELECT event_id, damage_property_usd FROM vw_storm_events_enriched ORDER BY event_id"
    )
    result = {r["event_id"]: r["damage_property_usd"] for r in rows}
    assert result["se-k"] == pytest.approx(10000.0)
    assert result["se-m"] == pytest.approx(2_500_000.0)
    assert result["se-b"] == pytest.approx(1_000_000_000.0)


def test_storm_damage_property_null_and_unparseable_yield_null(conn):
    insert_storm_event(conn, "se-null", "TX", "Hail", "01-JAN-19 00:00:00", damage_property=None)
    insert_storm_event(conn, "se-bad", "TX", "Hail", "01-JAN-19 00:00:00", damage_property="N/A")

    rows = fetch_all(
        conn, "SELECT event_id, damage_property_usd FROM vw_storm_events_enriched ORDER BY event_id"
    )
    result = {r["event_id"]: r["damage_property_usd"] for r in rows}
    assert result["se-bad"] is None
    assert result["se-null"] is None


def test_storm_total_injuries_and_deaths_sum_direct_and_indirect(conn):
    insert_storm_event(
        conn, "se-1", "TX", "Tornado", "01-JAN-19 00:00:00",
        injuries_direct=3, injuries_indirect=2, deaths_direct=1, deaths_indirect=0,
    )

    rows = fetch_all(
        conn, "SELECT total_injuries, total_deaths FROM vw_storm_events_enriched"
    )
    assert rows[0]["total_injuries"] == 5
    assert rows[0]["total_deaths"] == 1


def test_storm_total_injuries_treats_null_components_as_zero_in_sum_only(conn):
    insert_storm_event(
        conn, "se-1", "TX", "Tornado", "01-JAN-19 00:00:00",
        injuries_direct=None, injuries_indirect=None,
    )

    rows = fetch_all(
        conn, "SELECT injuries_direct, total_injuries FROM vw_storm_events_enriched"
    )
    assert rows[0]["injuries_direct"] is None  # raw column stays NULL, not coerced
    assert rows[0]["total_injuries"] == 0


def test_storm_daily_summary_no_double_counting_across_grain(conn):
    insert_storm_event(conn, "se-1", "TEXAS", "Tornado", "01-JAN-19 00:00:00", deaths_direct=1)
    insert_storm_event(conn, "se-2", "TEXAS", "Tornado", "01-JAN-19 06:00:00", deaths_direct=2)
    insert_storm_event(conn, "se-3", "OKLAHOMA", "Hail", "01-JAN-19 00:00:00", deaths_direct=0)

    rows = fetch_all(conn, "SELECT * FROM vw_storm_daily_summary ORDER BY state, event_type")

    texas_tornado = next(r for r in rows if r["state"] == "TEXAS" and r["event_type"] == "Tornado")
    assert texas_tornado["event_count"] == 2
    assert texas_tornado["total_deaths"] == 3
    assert texas_tornado["severe_event_count"] == 2

    oklahoma_hail = next(r for r in rows if r["state"] == "OKLAHOMA")
    assert oklahoma_hail["event_count"] == 1
    assert oklahoma_hail["severe_event_count"] == 0