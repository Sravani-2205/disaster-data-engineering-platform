"""
noaa_config.py

Genuinely configurable values for NOAA Storm Events ingestion.
Deliberately minimal -- no config framework.
"""

NOAA_CSVFILES_INDEX_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

DEFAULT_TIMEOUT_SECONDS = 30  # bulk CSV files can be several MB; USGS's 10s default is too tight

RAW_DATA_DIR = "data/raw/noaa"
