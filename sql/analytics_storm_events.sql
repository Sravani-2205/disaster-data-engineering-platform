-- sql/analytics_storm_events.sql
--
-- Analytical views over the storm_events table. Read-only views,
-- no schema changes.
--
-- begin_date_time is stored as raw NOAA text (e.g. "01-JAN-19
-- 00:00:00") by deliberate Stage C design -- it is parsed here,
-- at the analytical layer, rather than upstream. A value that
-- fails to parse yields NULL for begin_timestamp rather than
-- erroring the view.
--
-- damage_property / damage_crops are raw NOAA strings (e.g.
-- "10.00K", "25.00M", "1.50B") by deliberate Stage C design.
-- Parsed to numeric dollars here; unparseable/unexpected values
-- yield NULL (unknown), never 0.
--
-- Grain: one row per (source, event_id), matching storm_events'
-- primary key -- vw_storm_events_enriched preserves this grain;
-- vw_storm_daily_summary aggregates it explicitly.

CREATE VIEW vw_storm_events_enriched AS
SELECT
    source,
    event_id,
    state,
    event_type,
    begin_date_time,
    end_date_time,
    (CASE
        WHEN begin_date_time ~ '^\d{2}-[A-Z]{3}-\d{2} \d{2}:\d{2}:\d{2}$'
            THEN (to_timestamp(begin_date_time, 'DD-MON-YY HH24:MI:SS')::timestamp) AT TIME ZONE 'UTC'
        ELSE NULL
    END) AS begin_timestamp,
    injuries_direct,
    injuries_indirect,
    deaths_direct,
    deaths_indirect,
    COALESCE(injuries_direct, 0) + COALESCE(injuries_indirect, 0) AS total_injuries,
    COALESCE(deaths_direct, 0) + COALESCE(deaths_indirect, 0) AS total_deaths,
    (CASE
        WHEN damage_property IS NULL OR damage_property = '' THEN NULL
        WHEN damage_property ~* '^[0-9]+(\.[0-9]+)?K$'
            THEN CAST(LEFT(damage_property, LENGTH(damage_property) - 1) AS DOUBLE PRECISION) * 1000
        WHEN damage_property ~* '^[0-9]+(\.[0-9]+)?M$'
            THEN CAST(LEFT(damage_property, LENGTH(damage_property) - 1) AS DOUBLE PRECISION) * 1000000
        WHEN damage_property ~* '^[0-9]+(\.[0-9]+)?B$'
            THEN CAST(LEFT(damage_property, LENGTH(damage_property) - 1) AS DOUBLE PRECISION) * 1000000000
        WHEN damage_property ~ '^[0-9]+(\.[0-9]+)?$'
            THEN CAST(damage_property AS DOUBLE PRECISION)
        ELSE NULL
    END) AS damage_property_usd,
    (CASE
        WHEN damage_crops IS NULL OR damage_crops = '' THEN NULL
        WHEN damage_crops ~* '^[0-9]+(\.[0-9]+)?K$'
            THEN CAST(LEFT(damage_crops, LENGTH(damage_crops) - 1) AS DOUBLE PRECISION) * 1000
        WHEN damage_crops ~* '^[0-9]+(\.[0-9]+)?M$'
            THEN CAST(LEFT(damage_crops, LENGTH(damage_crops) - 1) AS DOUBLE PRECISION) * 1000000
        WHEN damage_crops ~* '^[0-9]+(\.[0-9]+)?B$'
            THEN CAST(LEFT(damage_crops, LENGTH(damage_crops) - 1) AS DOUBLE PRECISION) * 1000000000
        WHEN damage_crops ~ '^[0-9]+(\.[0-9]+)?$'
            THEN CAST(damage_crops AS DOUBLE PRECISION)
        ELSE NULL
    END) AS damage_crops_usd,
    begin_lat,
    begin_lon,
    magnitude,
    tor_f_scale
FROM storm_events;

CREATE VIEW vw_storm_daily_summary AS
SELECT
    date_trunc('day', begin_timestamp) AS event_date,
    state,
    event_type,
    COUNT(*) AS event_count,
    SUM(total_injuries) AS total_injuries,
    SUM(total_deaths) AS total_deaths,
    SUM(damage_property_usd) AS total_property_damage_usd,
    SUM(damage_crops_usd) AS total_crop_damage_usd,
    COUNT(*) FILTER (WHERE total_deaths > 0 OR total_injuries > 0) AS severe_event_count
FROM vw_storm_events_enriched
GROUP BY date_trunc('day', begin_timestamp), state, event_type;