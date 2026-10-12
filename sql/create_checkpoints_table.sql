-- sql/create_checkpoints_table.sql
--
-- Tracks the last successfully-processed ingestion window per source.
-- last_successful_run is the end_time of the most recent window that
-- was fetched, staged, validated, AND successfully loaded into
-- PostgreSQL. It only advances after a successful load -- never on
-- fetch/stage/validate/load failure.

CREATE TABLE ingestion_checkpoints (
    source              TEXT NOT NULL PRIMARY KEY,
    last_successful_run TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL
);
