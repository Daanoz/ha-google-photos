"""Constants for Google Photos."""
from __future__ import annotations

DOMAIN = "google_photos"
MANUFACTURER = "Google, Inc."
DATA_AUTH = "auth"
DEFAULT_ACCESS = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/photoslibrary.readonly",
]

CONF_ALBUM_ID = "album_id"
CONF_ALBUM_ID_FAVORITES = "FAVORITES"

CONF_MODE = "mode"
MODE_OPTION_RANDOM = "RANDOM"
MODE_OPTION_ALBUM_ORDER = "ALBUM_ORDER"
MODE_OPTIONS = [MODE_OPTION_RANDOM, MODE_OPTION_ALBUM_ORDER]
MODE_DEFAULT_OPTION = MODE_OPTION_RANDOM

CONF_INTERVAL = "interval"
INTERVAL_OPTION_NONE = "0"
INTERVAL_OPTION_10 = "10"
INTERVAL_OPTION_30 = "30"
INTERVAL_OPTION_60 = "60"
INTERVAL_OPTION_120 = "120"
INTERVAL_OPTION_300 = "300"
INTERVAL_OPTIONS = [
    INTERVAL_OPTION_NONE,
    INTERVAL_OPTION_10,
    INTERVAL_OPTION_30,
    INTERVAL_OPTION_60,
    INTERVAL_OPTION_120,
    INTERVAL_OPTION_300,
]
INTERVAL_DEFAULT_OPTION = INTERVAL_OPTION_60

CONF_WRITEMETADATA = "attribute_metadata"
WRITEMETADATA_DEFAULT_OPTION = False
