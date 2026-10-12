"""
noaa_pipeline.py

Responsibility: orchestrate one full NOAA Storm Events ingestion
cycle for a single requested year. Coordinates the existing NOAA
client, ingestion, staging, validation, loading, quarantine, and
checkpoint modules -- no parsing, validation, or SQL logic lives
here. Checkpoint architecture remains source-scoped (one row per
source, not per (source, year)); processing more than one year is
the caller's responsibility, one explicit call per year.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

import psycopg

from src.checkpointing.usgs_checkpoint import advance_checkpoint, get_checkpoint
from src.ingestion.noaa_client import list_storm_events_files
from src.ingestion.noaa_ingest import run_noaa_ingestion
from src.loading.noaa_loader import load_records
from src.quarantine.validation_failures import persist_rejected_records
from src.staging.noaa_staging import stage_storm_events
from src.validation.noaa_validation import validate_records


@dataclass
class NOAAPipelineRunResult:
    year: int
    source_file_creation_date: date | None
    inserted: int
    updated: int
    skipped: int
    rejected_count: int
    checkpoint_advanced_to: datetime | None
    skipped_run: bool


def _midnight_utc(day: date) -> datetime:
    """Represent a NOAA file creation date as midnight UTC for the
    TIMESTAMPTZ checkpoint column."""
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _skip_result(year: int, creation_date: date | None) -> NOAAPipelineRunResult:
    return NOAAPipelineRunResult(
        year=year,
        source_file_creation_date=creation_date,
        inserted=0,
        updated=0,
        skipped=0,
        rejected_count=0,
        checkpoint_advanced_to=None,
        skipped_run=True,
    )


def run_noaa_pipeline(
    conn: psycopg.Connection,
    year: int,
    source: str = "noaa",
) -> NOAAPipelineRunResult:
    """
    Run one NOAA Storm Events ingestion cycle for `year`.

    Sequence: checkpoint lookup -> resolve current published revision
    (listing only, no download) -> compare against checkpoint -> if
    not newer, no-op -> download raw file -> stage -> validate ->
    load valid records -> quarantine rejected records -> advance
    checkpoint only after load and quarantine both succeed.

    LoadError and QuarantineError propagate unmodified: on LoadError,
    quarantine is never attempted and the checkpoint is left
    unchanged; on QuarantineError, the checkpoint is left unchanged
    but any records already committed by load_records() remain
    committed (each stage commits its own transaction).
    """
    checkpoint = get_checkpoint(conn, source=source)

    available_files = list_storm_events_files()

    if year not in available_files:
        return _skip_result(year, creation_date=None)

    _, resolved_creation_date = available_files[year]
    resolved_checkpoint_value = _midnight_utc(resolved_creation_date)

    if checkpoint is not None and resolved_checkpoint_value <= checkpoint:
        return _skip_result(year, creation_date=resolved_creation_date)

    ingestion_result = run_noaa_ingestion(year)

    with open(ingestion_result.raw_file_path, "rb") as f:
        raw_bytes = f.read()

    staged_records = stage_storm_events(
        raw_bytes,
        source_file_year=ingestion_result.year,
        source_file_creation_date=ingestion_result.source_file_creation_date,
    )

    validation_result = validate_records(staged_records)

    load_result = load_records(validation_result.valid_records, conn, source=source)

    rejected_count = persist_rejected_records(
        validation_result.rejected_records, conn, source=source
    )

    checkpoint_value = _midnight_utc(ingestion_result.source_file_creation_date)
    advance_checkpoint(conn, checkpoint_value, source=source)

    return NOAAPipelineRunResult(
        year=year,
        source_file_creation_date=ingestion_result.source_file_creation_date,
        inserted=load_result.inserted,
        updated=load_result.updated,
        skipped=load_result.skipped,
        rejected_count=rejected_count,
        checkpoint_advanced_to=checkpoint_value,
        skipped_run=False,
    )