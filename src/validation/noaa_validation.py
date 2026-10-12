"""
noaa_validation.py

Responsibility: validate staged NOAA Storm Events records for
structural data quality. Pure in-memory function -- no filesystem
or database I/O. Never treats NULL as zero, never coerces NULL to
zero, never silently casts values.

Type boundary: staging is responsible for converting CSV strings
into appropriate Python types (int/float for numeric fields).
Validation only checks that those values are of the correct type
and, where applicable, within range -- it does not perform
corrective casting (e.g. "12" is never turned into 12 here).
"""

from src.validation.usgs_validation import RejectedRecord, ValidationResult

REQUIRED_STRING_FIELDS = ("event_id", "state", "event_type", "begin_date_time")

_LAT_FIELDS = ("begin_lat", "end_lat")
_LON_FIELDS = ("begin_lon", "end_lon")

_NUMERIC_OPTIONAL_FIELDS = ("magnitude", "begin_lat", "begin_lon", "end_lat", "end_lon")

_INTEGER_OPTIONAL_FIELDS = (
    "injuries_direct",
    "injuries_indirect",
    "deaths_direct",
    "deaths_indirect",
)


def _is_numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_record(record: dict) -> list[str]:
    reasons = []

    # Required string fields
    for field in REQUIRED_STRING_FIELDS:
        value = record.get(field)
        if value is None or value == "":
            reasons.append(f"{field} is missing or empty")

    # Numeric fields (magnitude, begin/end lat/lon): NULL is valid,
    # only check type (and range for lat/lon) when present.
    for field in _NUMERIC_OPTIONAL_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if not _is_numeric(value):
            reasons.append(f"{field} {value!r} is not numeric")
            continue
        if field in _LAT_FIELDS and not (-90 <= value <= 90):
            reasons.append(f"{field} {value!r} is out of range (-90 to 90)")
        elif field in _LON_FIELDS and not (-180 <= value <= 180):
            reasons.append(f"{field} {value!r} is out of range (-180 to 180)")

    # Integer fields (injury/death counts): NULL is valid, only
    # check type when present.
    for field in _INTEGER_OPTIONAL_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if not _is_integer(value):
            reasons.append(f"{field} {value!r} is not an integer")

    return reasons


def validate_records(staged_records: list[dict]) -> ValidationResult:
    """
    Validate a list of staged NOAA Storm Events records.

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
