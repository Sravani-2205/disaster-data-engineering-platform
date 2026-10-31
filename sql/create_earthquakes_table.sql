-- sql/create_earthquakes_table.sql
--
-- Creates the analytical earthquakes table (source: USGS).
-- This table holds validated records only. Staging is in-memory,
-- and rejected records are stored in validation_failures.

CREATE TABLE earthquakes (
    source        TEXT NOT NULL,
    event_id      TEXT NOT NULL,
    time          TIMESTAMPTZ NOT NULL,
    updated       TIMESTAMPTZ NOT NULL,
    magnitude     DOUBLE PRECISION,
    place         TEXT,
    latitude      DOUBLE PRECISION NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL,
    depth         DOUBLE PRECISION,
    ingested_at   TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (source, event_id),
    CONSTRAINT chk_latitude_range CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT chk_longitude_range CHECK (longitude BETWEEN -180 AND 180)
);

CREATE INDEX idx_earthquakes_time ON earthquakes (time);
