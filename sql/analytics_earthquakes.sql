-- sql/analytics_earthquakes.sql
--
-- Analytical views over the earthquakes table. Read-only views,
-- no schema changes, no duplication of loader/validation logic.
-- Grain of earthquakes is already one row per (source, event_id);
-- these views preserve that grain except where explicitly
-- aggregating (vw_earthquake_daily_summary).
--
-- NULL handling: magnitude/depth NULLs are preserved as unknown,
-- never coalesced to zero -- an earthquake with unknown magnitude
-- is not the same as a magnitude-zero event.

CREATE VIEW vw_earthquakes_enriched AS
SELECT
    source,
    event_id,
    time,
    updated,
    magnitude,
    place,
    latitude,
    longitude,
    depth,
    date_trunc('day', time) AS event_date,
    (magnitude IS NOT NULL AND magnitude >= 6.0) AS is_significant
FROM earthquakes;

CREATE VIEW vw_earthquake_daily_summary AS
SELECT
    date_trunc('day', time) AS event_date,
    COUNT(*) AS event_count,
    COUNT(*) FILTER (WHERE magnitude IS NOT NULL AND magnitude >= 6.0) AS significant_count,
    AVG(magnitude) AS avg_magnitude,
    MAX(magnitude) AS max_magnitude,
    AVG(depth) AS avg_depth
FROM earthquakes
GROUP BY date_trunc('day', time);