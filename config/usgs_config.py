"""
usgs_config.py

Genuinely configurable values for USGS ingestion.
Deliberately minimal -- no config framework, no env-loading logic.
"""

USGS_BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

DEFAULT_TIMEOUT_SECONDS = 10

RAW_DATA_DIR = "data/raw/usgs"
