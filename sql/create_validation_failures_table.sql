-- sql/create_validation_failures_table.sql
--
-- Durable, append-only audit log of validation-rejected records.
-- No uniqueness constraint on (source, event_id): duplicate rows on
-- window replay are intentional (see Milestone 8 design) -- this
-- table's value is completeness, not deduplication.

CREATE TABLE validation_failures (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    event_id     TEXT,
    record       JSONB NOT NULL,
    reasons      TEXT[] NOT NULL,
    rejected_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_validation_failures_source_event_id
    ON validation_failures (source, event_id);

CREATE INDEX idx_validation_failures_rejected_at
    ON validation_failures (rejected_at);
