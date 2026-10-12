"""
usgs_pipeline.py

Responsibility: sequence the existing USGS pipeline components --
fetch, stage, validate, load, checkpoint -- for one run. Contains no
domain logic of its own; each step's behavior/correctness lives in
its own module. This function only decides the order of calls and
what window/parameters to use.

No try/except here: exceptions from any step propagate to the
caller unchanged, and the checkpoint is only advanced if every prior
step completed without raising.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg

from src.ingestion.usgs_client import fetch_earthquake_data
from src.staging.usgs_staging import stage_features
from src.validation.usgs_validation import validate_records
from src.loading.usgs_loader import load_records
from src.quarantine.validation_failures import persist_rejected_records
from src.checkpointing.usgs_checkpoint import get_checkpoint, advance_checkpoint


@dataclass
class PipelineRunResult:
    inserted: int
    updated: int
    skipped: int
    rejected_count: int
    checkpoint_advanced_to: datetime


def run_usgs_pipeline(
    conn: psycopg.Connection,
    historical_start_time: str | None = None,
    end_time: str | None = None,
    source: str = "usgs",
) -> PipelineRunResult:
    """
    Run one full USGS ingestion cycle:
    checkpoint -> determine window -> fetch -> stage -> validate ->
    load -> advance checkpoint (only on success).

    Args:
        conn: an open psycopg connection.
        historical_start_time: ISO date/time string used as the
            USGS `starttime` query bound. Required on the very
            first run (when no checkpoint exists yet) -- raises
            ValueError if omitted in that case. On subsequent
            (incremental) runs this is still required and is used
            as a fixed, wide `starttime` bound; the actual
            incremental filter is `updatedafter`, set from the
            stored checkpoint. This deliberately keeps "how far
            back starttime reaches" and "what's new since last run"
            as two separate, explicit concepts -- see design notes.
        end_time: ISO date/time string for the USGS `endtime` bound
            and the value the checkpoint will advance to on success.
            Defaults to the current UTC time, resolved once at the
            start of this call.
        source: source identifier, used for both the earthquakes
            table and the checkpoint row.

    Returns:
        PipelineRunResult summarizing what happened.

    Raises:
        Whatever fetch_earthquake_data, stage_features,
        or load_records raise. On any such exception, the
        checkpoint is left completely unchanged, since the
        advance_checkpoint() call is only reached after every
        prior step has succeeded.
    """
    resolved_end_time = end_time or datetime.now(timezone.utc).isoformat()

    existing_checkpoint = get_checkpoint(conn, source=source)

    if existing_checkpoint is None:
        if historical_start_time is None:
            raise ValueError(
                "No checkpoint exists for source "
                f"{source!r}; historical_start_time is required."
            )
        updated_after = None
    else:
        if historical_start_time is None:
            raise ValueError(
                "historical_start_time is required as the starttime "
                "bound even on incremental runs; updatedafter alone "
                "does not bound starttime."
            )
        # Postgres returns TIMESTAMPTZ values adjusted to the session's
        # local timezone. Normalize to UTC before formatting so
        # updatedafter is always expressed in a consistent, predictable
        # offset regardless of server/session timezone settings.
        updated_after = existing_checkpoint.astimezone(timezone.utc).isoformat()

    payload = fetch_earthquake_data(
        historical_start_time,
        resolved_end_time,
        updated_after=updated_after,
    )
    staged = stage_features(payload)
    validation_result = validate_records(staged)
    load_result = load_records(validation_result.valid_records, conn, source=source)

    # Reached only if load_records() did not raise.
    persist_rejected_records(validation_result.rejected_records, conn, source=source)

    # Reached only if persist_rejected_records() also did not raise.
    checkpoint_value = datetime.fromisoformat(resolved_end_time)
    advance_checkpoint(conn, checkpoint_value, source=source)

    return PipelineRunResult(
        inserted=load_result.inserted,
        updated=load_result.updated,
        skipped=load_result.skipped,
        rejected_count=len(validation_result.rejected_records),
        checkpoint_advanced_to=checkpoint_value,
    )
