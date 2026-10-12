"""
pipeline_runner.py

Responsibility: coordinate one run of the USGS pipeline and one run
of the NOAA pipeline against a shared connection, isolating failures
between them. Contains no domain logic -- run_usgs_pipeline() and
run_noaa_pipeline() are called exactly as designed, unmodified.

This is the one place in the system that catches pipeline-level
exceptions rather than letting them propagate to the caller: each
source's failure must not prevent the other source from running.
Each source's own internal guarantees (checkpoint only advances on
full success, quarantine/load semantics, idempotency) are entirely
unaffected -- this module only decides what happens after a source's
run either returns or raises.
"""

from dataclasses import dataclass

import psycopg

from src.orchestration.usgs_pipeline import PipelineRunResult, run_usgs_pipeline
from src.orchestration.noaa_pipeline import (
    NOAAPipelineRunResult,
    run_noaa_pipeline,
)


@dataclass
class SourceOutcome:
    source: str
    succeeded: bool
    result: PipelineRunResult | NOAAPipelineRunResult | None
    error: BaseException | None


@dataclass
class IntegratedPipelineRunResult:
    usgs: SourceOutcome
    noaa: SourceOutcome


def _run_source(
    conn: psycopg.Connection, source_name: str, fn, *args, **kwargs
) -> SourceOutcome:
    try:
        result = fn(*args, **kwargs)
        return SourceOutcome(
            source=source_name, succeeded=True, result=result, error=None
        )
    except Exception as exc:  # noqa: BLE001 -- intentionally broad: this is the
        # one place responsible for isolating failures between sources.
        # Roll back defensively: some failures (e.g. a checkpoint-advance
        # error) may leave the connection in an aborted transaction state
        # without having rolled back themselves, since that has never
        # mattered when a connection was only ever used for one pipeline
        # call. Rolling back here ensures the other source's run starts
        # from a clean connection regardless of where the prior failure
        # occurred.
        conn.rollback()
        return SourceOutcome(
            source=source_name, succeeded=False, result=None, error=exc
        )


def run_all_pipelines(
    conn: psycopg.Connection,
    usgs_historical_start_time: str | None,
    usgs_end_time: str | None,
    noaa_year: int,
) -> IntegratedPipelineRunResult:
    """
    Run one USGS ingestion cycle and one NOAA ingestion cycle for
    `noaa_year`, using the same connection.

    Each source's run is fully isolated: a failure in one does not
    prevent the other from running, and does not alter the other's
    checkpoint or data. Each source's own semantics (documented in
    run_usgs_pipeline and run_noaa_pipeline) are unchanged -- this
    function only decides what happens after each call returns or
    raises, and never re-raises: failures are reported in the
    returned result instead, since a caller of *this* function is
    asking for both sources' outcomes, not just whichever ran first.
    """
    usgs_outcome = _run_source(
        conn,
        "usgs",
        run_usgs_pipeline,
        conn,
        usgs_historical_start_time,
        usgs_end_time,
    )

    noaa_outcome = _run_source(
        conn,
        "noaa",
        run_noaa_pipeline,
        conn,
        noaa_year,
    )

    return IntegratedPipelineRunResult(usgs=usgs_outcome, noaa=noaa_outcome)