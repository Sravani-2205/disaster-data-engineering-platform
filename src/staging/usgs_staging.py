"""
usgs_staging.py

Responsibility: reshape a raw USGS GeoJSON payload into a flat list
of row-like dicts. No type conversion, no validation, no cleaning.
"""


def stage_features(raw_payload: dict) -> list[dict]:
    """
    Flatten each feature in a raw USGS GeoJSON payload into a flat dict.

    Does not validate, convert types, or handle nulls -- values are
    passed through exactly as USGS provided them.
    """
    staged = []

    for feature in raw_payload["features"]:
        properties = feature["properties"]
        coordinates = feature["geometry"]["coordinates"]

        staged.append({
            "event_id": feature["id"],
            "time": properties["time"],
            "updated": properties["updated"],
            "magnitude": properties["mag"],
            "place": properties["place"],
            "longitude": coordinates[0],
            "latitude": coordinates[1],
            "depth": coordinates[2],
        })

    return staged
