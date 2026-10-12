CREATE TABLE storm_events (
    source                    TEXT NOT NULL DEFAULT 'noaa',
    event_id                  TEXT NOT NULL,
    episode_id                TEXT,
    state                     TEXT NOT NULL,
    event_type                TEXT NOT NULL,
    cz_type                   TEXT,
    cz_fips                   TEXT,
    cz_name                   TEXT,
    begin_date_time           TEXT NOT NULL,
    end_date_time             TEXT,
    cz_timezone               TEXT,
    injuries_direct           INTEGER,
    injuries_indirect         INTEGER,
    deaths_direct             INTEGER,
    deaths_indirect           INTEGER,
    damage_property            TEXT,
    damage_crops              TEXT,
    magnitude                 DOUBLE PRECISION,
    magnitude_type             TEXT,
    tor_f_scale                TEXT,
    begin_lat                 DOUBLE PRECISION,
    begin_lon                 DOUBLE PRECISION,
    end_lat                   DOUBLE PRECISION,
    end_lon                   DOUBLE PRECISION,
    source_file_year           INTEGER NOT NULL,
    source_file_creation_date  DATE NOT NULL,
    ingested_at                TIMESTAMPTZ NOT NULL,

    PRIMARY KEY (source, event_id),

    CONSTRAINT chk_begin_lat_range
        CHECK (begin_lat IS NULL OR begin_lat BETWEEN -90 AND 90),

    CONSTRAINT chk_begin_lon_range
        CHECK (begin_lon IS NULL OR begin_lon BETWEEN -180 AND 180),

    CONSTRAINT chk_end_lat_range
        CHECK (end_lat IS NULL OR end_lat BETWEEN -90 AND 90),

    CONSTRAINT chk_end_lon_range
        CHECK (end_lon IS NULL OR end_lon BETWEEN -180 AND 180)
);

CREATE INDEX idx_storm_events_begin_date_time
    ON storm_events (begin_date_time);

CREATE INDEX idx_storm_events_event_type
    ON storm_events (event_type);
