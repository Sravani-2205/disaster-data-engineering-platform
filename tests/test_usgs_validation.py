"""
test_usgs_validation.py

Tests for validate_records(). Pure in-memory, no mocking needed.
"""

from src.validation.usgs_validation import validate_records


def make_valid_record(**overrides):
    base = {
        "event_id": "ci11408890",
        "time": 1388620296020,
        "updated": 1457728844428,
        "magnitude": 1.29,
        "place": "10km SSW of Idyllwild, CA",
        "longitude": -116.7776667,
        "latitude": 33.6633333,
        "depth": 11.008,
    }
    base.update(overrides)
    return base


def test_all_valid_batch_passes():
    records = [make_valid_record(), make_valid_record(event_id="b")]

    result = validate_records(records)

    assert len(result.valid_records) == 2
    assert result.rejected_records == []


def test_missing_event_id_is_rejected():
    records = [make_valid_record(event_id=None)]

    result = validate_records(records)

    assert result.valid_records == []
    assert len(result.rejected_records) == 1
    assert "event_id is missing or empty" in result.rejected_records[0].reasons


def test_missing_time_is_rejected():
    records = [make_valid_record(time=None)]

    result = validate_records(records)

    assert "time is missing" in result.rejected_records[0].reasons


def test_missing_updated_is_rejected():
    records = [make_valid_record(updated=None)]

    result = validate_records(records)

    assert "updated is missing" in result.rejected_records[0].reasons


def test_invalid_latitude_is_rejected():
    records = [make_valid_record(latitude=95.2)]

    result = validate_records(records)

    assert len(result.rejected_records) == 1
    assert any("latitude" in r for r in result.rejected_records[0].reasons)


def test_invalid_longitude_is_rejected():
    records = [make_valid_record(longitude=200)]

    result = validate_records(records)

    assert len(result.rejected_records) == 1
    assert any("longitude" in r for r in result.rejected_records[0].reasons)


def test_null_magnitude_is_valid():
    records = [make_valid_record(magnitude=None)]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.rejected_records == []


def test_null_depth_is_valid():
    records = [make_valid_record(depth=None)]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.rejected_records == []


def test_multiple_simultaneous_failures_are_all_reported():
    records = [make_valid_record(event_id=None, latitude=999, longitude=999)]

    result = validate_records(records)

    reasons = result.rejected_records[0].reasons
    assert len(reasons) == 3
    assert any("event_id" in r for r in reasons)
    assert any("latitude" in r for r in reasons)
    assert any("longitude" in r for r in reasons)


def test_empty_input_returns_empty_result():
    result = validate_records([])

    assert result.valid_records == []
    assert result.rejected_records == []


def test_mixed_batch_preserves_order_in_each_list():
    good_a = make_valid_record(event_id="good-a")
    bad = make_valid_record(event_id=None)
    good_b = make_valid_record(event_id="good-b")

    result = validate_records([good_a, bad, good_b])

    assert [r["event_id"] for r in result.valid_records] == ["good-a", "good-b"]
    assert len(result.rejected_records) == 1
    assert result.rejected_records[0].record["event_id"] is None
    # original staged record preserved unchanged
    assert result.rejected_records[0].record == bad
