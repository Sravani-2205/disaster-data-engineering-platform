"""
usgs_validation.py

Responsibility: validate staged USGS records for structural data
quality. Pure in-memory function -- no filesystem or database I/O.
Never treats NULL as zero, never coerces NULL to zero.
"""

from dataclasses import dataclass


@dataclass
class RejectedRecord:
    record: dict
    reasons: list[str]


@dataclass
class ValidationResult:
    valid_records: list[dict]
    rejected_records: list[RejectedRecord]


def _is_numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_record(record: dict) -> list[str]:
    reasons = []

    event_id = record.get("event_id")
    if not event_id:
        reasons.append("event_id is missing or empty")

    time = record.get("time")
    if time is None:
        reasons.append("time is missing")
    elif not _is_numeric(time):
        reasons.append(f"time {time!r} is not numeric")

    updated = record.get("updated")
    if updated is None:
        reasons.append("updated is missing")
    elif not _is_numeric(updated):
        reasons.append(f"updated {updated!r} is not numeric")

    latitude = record.get("latitude")
    if latitude is None:
        reasons.append("latitude is missing")
    elif not _is_numeric(latitude):
        reasons.append(f"latitude {latitude!r} is not numeric")
    elif not (-90 <= latitude <= 90):
        reasons.append(f"latitude {latitude!r} is out of range (-90 to 90)")

    longitude = record.get("longitude")
    if longitude is None:
        reasons.append("longitude is missing")
    elif not _is_numeric(longitude):
        reasons.append(f"longitude {longitude!r} is not numeric")
    elif not (-180 <= longitude <= 180):
        reasons.append(f"longitude {longitude!r} is out of range (-180 to 180)")

    # magnitude: NULL is fully valid, only check type when present
    magnitude = record.get("magnitude")
    if magnitude is not None and not _is_numeric(magnitude):
        reasons.append(f"magnitude {magnitude!r} is not numeric")

    # depth: NULL is fully valid, only check type when present
    depth = record.get("depth")
    if depth is not None and not _is_numeric(depth):
        reasons.append(f"depth {depth!r} is not numeric")

    # place: NULL is fully valid, only check type when present
    place = record.get("place")
    if place is not None and not isinstance(place, str):
        reasons.append(f"place {place!r} is not a string")

    return reasons


def validate_records(staged_records: list[dict]) -> ValidationResult:
    """
    Validate a list of staged USGS records.

    Returns a ValidationResult splitting input into valid_records
    (unchanged) and rejected_records (original record preserved,
    paired with one or more human-readable rejection reasons).
    """
    valid_records = []
    rejected_records = []

    for record in staged_records:
        reasons = _validate_record(record)
        if reasons:
            rejected_records.append(RejectedRecord(record=record, reasons=reasons))
        else:
            valid_records.append(record)

    return ValidationResult(valid_records=valid_records, rejected_records=rejected_records)
