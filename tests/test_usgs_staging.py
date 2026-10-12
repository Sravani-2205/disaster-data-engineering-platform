"""
test_usgs_staging.py

Tests for stage_features(). No mocking needed -- pure function,
in-memory dicts only.
"""

from src.staging.usgs_staging import stage_features


def test_stage_features_flattens_single_feature():
    raw_payload = {
        "features": [
            {
                "id": "ci11408890",
                "properties": {
                    "time": 1388620296020,
                    "updated": 1457728844428,
                    "mag": 1.29,
                    "place": "10km SSW of Idyllwild, CA",
                },
                "geometry": {
                    "coordinates": [-116.7776667, 33.6633333, 11.008],
                },
            }
        ]
    }

    result = stage_features(raw_payload)

    assert result == [
        {
            "event_id": "ci11408890",
            "time": 1388620296020,
            "updated": 1457728844428,
            "magnitude": 1.29,
            "place": "10km SSW of Idyllwild, CA",
            "longitude": -116.7776667,
            "latitude": 33.6633333,
            "depth": 11.008,
        }
    ]


def test_stage_features_handles_multiple_features():
    raw_payload = {
        "features": [
            {
                "id": "a",
                "properties": {"time": 1, "updated": 2, "mag": 3.0, "place": "X"},
                "geometry": {"coordinates": [10, 20, 30]},
            },
            {
                "id": "b",
                "properties": {"time": 4, "updated": 5, "mag": 6.0, "place": "Y"},
                "geometry": {"coordinates": [40, 50, 60]},
            },
        ]
    }

    result = stage_features(raw_payload)

    assert len(result) == 2
    assert result[0]["event_id"] == "a"
    assert result[1]["event_id"] == "b"


def test_stage_features_handles_empty_feature_list():
    raw_payload = {"features": []}

    result = stage_features(raw_payload)

    assert result == []


def test_stage_features_passes_through_null_values_unchanged():
    """
    Confirms staging does NOT do NULL handling -- a null magnitude
    should stay None, not become 0 or get dropped.
    """
    raw_payload = {
        "features": [
            {
                "id": "c",
                "properties": {"time": 1, "updated": 2, "mag": None, "place": None},
                "geometry": {"coordinates": [10, 20, 30]},
            }
        ]
    }

    result = stage_features(raw_payload)

    assert result[0]["magnitude"] is None
    assert result[0]["place"] is None
