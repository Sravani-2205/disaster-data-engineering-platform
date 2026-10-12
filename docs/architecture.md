# Disaster Data Engineering & Intelligence Platform

## 1. Project Objective

Turn two public disaster datasets, USGS earthquakes and NOAA storm events, into a trustworthy analytical database and a Power BI dashboard. The engineering goals were:

- Load data **incrementally**, so a run only fetches what is new.
- Make every load **idempotent**, so re-running never duplicates rows.
- **Never silently drop** bad records: keep them for inspection.
- Keep each source **independent**, so one failing source never blocks the other.

## 2. Architecture Overview

```
USGS API ─┐
          ├─> Ingest ─> Stage ─> Validate ─> Load ─> PostgreSQL ─> Power BI
NOAA files┘                         │          │
                                    v          v
                               Quarantine   Checkpoint
```

Each source has its own pipeline function (`run_usgs_pipeline`, `run_noaa_pipeline`). A thin integration layer, `pipeline_runner.py`, runs both against one connection and reports each outcome separately. The pipelines contain only sequencing. Parsing, validation and SQL each live in their own module.

## 3. Data Sources

| Source | Format | Unit of work |
|---|---|---|
| USGS Earthquake Catalog (FDSN event API) | GeoJSON over HTTP | A date window |
| NOAA NCEI Storm Events Database | Yearly CSV files | One year per call |

USGS limits a single request to 20,000 events. Large historical loads therefore split into smaller date windows (see section 13).

## 4. Ingestion Layer

- **USGS:** `fetch_earthquake_data(start, end, updated_after)` queries the API for events in a window.
- **NOAA:** `list_storm_events_files()` lists the published yearly files and their creation dates, and `run_noaa_ingestion(year)` downloads one file.

The USGS pipeline separates two ideas on purpose: `starttime` bounds how far back to look, and `updatedafter` (taken from the stored checkpoint) selects what changed since the last run.

## 5. Raw Data Layer

Downloaded source files are kept locally under `data/raw/` and are excluded from git. Parsing starts from the raw bytes, so a run is reproducible from the file that was downloaded.

## 6. Staging Layer

`stage_features` (USGS) and `stage_storm_events` (NOAA) turn raw payloads into consistent, typed records. NOAA staging also records the source file's year and creation date on every record.

## 7. Validation Layer

`validate_records` splits staged records into **valid** and **rejected**. Valid records go on to loading. Rejected records go to the shared quarantine module, which stores them in the `validation_failures` table for later inspection instead of discarding them.

## 8. PostgreSQL Layer

| Table | Purpose |
|---|---|
| `earthquakes` | USGS events, primary key `(source, event_id)` |
| `storm_events` | NOAA events, primary key `(source, event_id)` |
| `ingestion_checkpoints` | One row per source |
| `validation_failures` | Quarantined records |

Tables carry database-level constraints, such as latitude and longitude range checks. Four analytical views (`sql/analytics_*.sql`) feed the Power BI report.

## 9. Incremental Processing

- **USGS:** after the first run, requests pass `updatedafter` set from the stored checkpoint (normalized to UTC), so only new or changed events are fetched.
- **NOAA:** a year is processed only when its published file is newer than the checkpoint. Otherwise the run is a no-op.

Loading is idempotent. Loaders report `inserted`, `updated` and `skipped` counts: new events are inserted, changed events are updated, and unchanged events are skipped. Re-running a window is safe.

## 10. Checkpoint Management

The checkpoint is one row per source in `ingestion_checkpoints`, holding the last successful run.

- It advances **only after every earlier step succeeded**: fetch, stage, validate, load and quarantine.
- If any step raises, the checkpoint stays unchanged and the next run retries.
- The NOAA checkpoint is source-scoped, not per year. Backfilling several years therefore resets it before each year (see section 13).

## 11. Failure Handling

- The individual pipelines have no `try/except`: exceptions propagate unchanged, which keeps their behavior simple and the checkpoint rule easy to reason about.
- `pipeline_runner.py` is the one place that catches pipeline-level exceptions. Each source's failure is recorded in the result, and the connection is rolled back so the other source starts from a clean state.
- Each stage commits its own transaction. If quarantine fails after loading, the loaded records stay committed but the checkpoint does not advance, and a rerun is safe because of idempotent loads.

## 12. Testing Strategy

The suite has 155+ automated tests with pytest, covering each layer separately (clients, ingestion, staging, validation, loading, quarantine, checkpointing) plus the orchestration and the analytical views. Integration tests run against a real PostgreSQL instance, with the password supplied through the `POSTGRES_PASSWORD` environment variable.

## 13. Engineering Decisions

- **Quarantine over dropping.** Rejected records are kept and queryable.
- **Checkpoint after success only.** A failed run never moves progress forward.
- **Source isolation at one point.** The runner is the only place that swallows exceptions, so failures stay visible everywhere else.
- **Windowed backfills.** When scaling from a two-day sample to ten years, USGS's 20,000-event request cap broke a dense window (the 2019 Ridgecrest earthquake sequence). The backfill script now counts events first and splits any window over the limit.
- **Checkpoint reset for NOAA backfills.** Because the checkpoint is not per year, older years would be skipped. The backfill clears the NOAA checkpoint before each year, which is safe because loads are idempotent.
- **Timezone discipline.** USGS timestamps are normalized to UTC. Yearly counts checked in IST differed slightly from UTC until grouped in UTC.
- **No scheduler.** Updates run on demand with one command (`update_data.bat`), then a manual Power BI refresh. A scheduled run would be a natural next step.
