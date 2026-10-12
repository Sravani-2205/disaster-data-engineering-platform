"""
test_noaa_validation.py

Tests for validate_records() (NOAA). Pure in-memory, no mocking
needed. Staged records here use already-typed values (int/float)
for numeric fields per the Stage D type boundary, matching what
staging is expected to hand off to validation.
"""

from src.validation.noaa_validation import validate_records


def make_valid_record(**overrides):
    base = {
        "event_id": "10001",
        "episode_id": "5001",
        "state": "TEXAS",
        "event_type": "Tornado",
        "cz_type": "C",
        "cz_fips": "201",
        "cz_name": "TRAVIS",
        "begin_date_time": "01-JAN-19 14:00:00",
        "end_date_time": "01-JAN-19 14:15:00",
        "cz_timezone": "CST-6",
        "injuries_direct": 2,
        "injuries_indirect": 0,
        "deaths_direct": 1,
        "deaths_indirect": 0,
        "damage_property": "10.00K",
        "damage_crops": "5.00M",
        "magnitude": 1.5,
        "magnitude_type": "EG3",
        "tor_f_scale": "F1",
        "begin_lat": 30.27,
        "begin_lon": -97.74,
        "end_lat": 30.30,
        "end_lon": -97.70,
        "source_file_year": 2019,
        "source_file_creation_date": "2020-02-19",
    }
    base.update(overrides)
    return base


def test_completely_valid_record_passes():
    records = [make_valid_record()]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.rejected_records == []


def test_missing_event_id_is_rejected():
    records = [make_valid_record(event_id=None)]

    result = validate_records(records)

    assert result.valid_records == []
    assert "event_id is missing or empty" in result.rejected_records[0].reasons


def test_missing_state_is_rejected():
    records = [make_valid_record(state=None)]

    result = validate_records(records)

    assert "state is missing or empty" in result.rejected_records[0].reasons


def test_missing_event_type_is_rejected():
    records = [make_valid_record(event_type=None)]

    result = validate_records(records)

    assert "event_type is missing or empty" in result.rejected_records[0].reasons


def test_missing_begin_date_time_is_rejected():
    records = [make_valid_record(begin_date_time=None)]

    result = validate_records(records)

    assert "begin_date_time is missing or empty" in result.rejected_records[0].reasons


def test_empty_string_required_field_is_rejected():
    records = [make_valid_record(state="")]

    result = validate_records(records)

    assert "state is missing or empty" in result.rejected_records[0].reasons


def test_invalid_begin_lat_is_rejected():
    records = [make_valid_record(begin_lat=95.0)]

    result = validate_records(records)

    assert any("begin_lat" in r for r in result.rejected_records[0].reasons)


def test_invalid_begin_lon_is_rejected():
    records = [make_valid_record(begin_lon=200.0)]

    result = validate_records(records)

    assert any("begin_lon" in r for r in result.rejected_records[0].reasons)


def test_invalid_end_lat_is_rejected():
    records = [make_valid_record(end_lat=-95.0)]

    result = validate_records(records)

    assert any("end_lat" in r for r in result.rejected_records[0].reasons)


def test_invalid_end_lon_is_rejected():
    records = [make_valid_record(end_lon=-200.0)]

    result = validate_records(records)

    assert any("end_lon" in r for r in result.rejected_records[0].reasons)


def test_non_numeric_lat_lon_is_rejected():
    records = [make_valid_record(begin_lat="30.27", begin_lon="-97.74")]

    result = validate_records(records)

    reasons = result.rejected_records[0].reasons
    assert any("begin_lat" in r and "not numeric" in r for r in reasons)
    assert any("begin_lon" in r and "not numeric" in r for r in reasons)


def test_non_numeric_magnitude_is_rejected():
    records = [make_valid_record(magnitude="1.5")]

    result = validate_records(records)

    assert any("magnitude" in r and "not numeric" in r for r in result.rejected_records[0].reasons)


def test_boolean_is_not_accepted_as_numeric():
    records = [make_valid_record(magnitude=True)]

    result = validate_records(records)

    assert any("magnitude" in r and "not numeric" in r for r in result.rejected_records[0].reasons)


def test_boolean_is_not_accepted_as_integer():
    records = [make_valid_record(injuries_direct=True)]

    result = validate_records(records)

    assert any("injuries_direct" in r and "not an integer" in r for r in result.rejected_records[0].reasons)


def test_nullable_numeric_fields_with_none_pass():
    records = [make_valid_record(
        magnitude=None, begin_lat=None, begin_lon=None, end_lat=None, end_lon=None
    )]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.rejected_records == []


def test_valid_integer_injury_death_fields_pass():
    records = [make_valid_record(
        injuries_direct=3, injuries_indirect=1, deaths_direct=0, deaths_indirect=2
    )]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.rejected_records == []


def test_nullable_integer_fields_with_none_pass():
    records = [make_valid_record(
        injuries_direct=None, injuries_indirect=None, deaths_direct=None, deaths_indirect=None
    )]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.rejected_records == []


def test_invalid_injury_death_types_rejected():
    records = [make_valid_record(injuries_direct="2", deaths_indirect=1.5)]

    result = validate_records(records)

    reasons = result.rejected_records[0].reasons
    assert any("injuries_direct" in r and "not an integer" in r for r in reasons)
    assert any("deaths_indirect" in r and "not an integer" in r for r in reasons)


def test_damage_strings_remain_valid_and_unchanged():
    records = [make_valid_record(damage_property="10.00K", damage_crops="5.00M")]

    result = validate_records(records)

    assert len(result.valid_records) == 1
    assert result.valid_records[0]["damage_property"] == "10.00K"
    assert result.valid_records[0]["damage_crops"] == "5.00M"


def test_multiple_simultaneous_failures_are_all_reported():
    records = [make_valid_record(event_id=None, begin_lat=999.0, begin_lon=999.0)]

    result = validate_records(records)

    reasons = result.rejected_records[0].reasons
    assert len(reasons) == 3
    assert any("event_id" in r for r in reasons)
    assert any("begin_lat" in r for r in reasons)
    assert any("begin_lon" in r for r in reasons)


def test_empty_input_returns_empty_result():
    result = validate_records([])

    assert result.valid_records == []
    assert result.rejected_records == []


def test_mixed_batch_preserves_order_and_rejected_records_unchanged():
    good_a = make_valid_record(event_id="good-a")
    bad = make_valid_record(event_id=None)
    good_b = make_valid_record(event_id="good-b")

    result = validate_records([good_a, bad, good_b])

    assert [r["event_id"] for r in result.valid_records] == ["good-a", "good-b"]
    assert len(result.rejected_records) == 1
    assert result.rejected_records[0].record["event_id"] is None
    assert result.rejected_records[0].record == bad


def test_validation_does_not_cast_string_numerics():
    """
    A string numeric like "12" or "1.5" must be rejected as
    non-numeric/non-integer, never silently cast to a number.
    """
    records = [make_valid_record(magnitude="1.5", injuries_direct="12")]

    result = validate_records(records)

    reasons = result.rejected_records[0].reasons
    assert any("magnitude" in r and "not numeric" in r for r in reasons)
    assert any("injuries_direct" in r and "not an integer" in r for r in reasons)
    # confirm original strings were preserved, not converted
    assert result.rejected_records[0].record["magnitude"] == "1.5"
    assert result.rejected_records[0].record["injuries_direct"] == "12"
