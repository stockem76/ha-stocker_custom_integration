"""Constants for the Stocker Custom Integration."""

DOMAIN = "stocker_custom_integration"
DEFAULT_NAME = "Stocker Vision"

CONF_TOPIC_PREFIX = "topic_prefix"
CONF_CERTAIN_THRESHOLD = "certain_threshold"
CONF_LIKELY_THRESHOLD = "likely_threshold"
CONF_COOLDOWN = "cooldown"
CONF_UNKNOWN_DELAY = "unknown_delay"
CONF_UNKNOWN_CAMERAS = "unknown_cameras"
CONF_ANNOUNCE_UNKNOWN_VEHICLES = "announce_unknown_vehicles"
CONF_PRESENCE_MINUTES = "presence_minutes"

DEFAULT_TOPIC_PREFIX = "frigate"
DEFAULT_CERTAIN_THRESHOLD = 0.9
DEFAULT_LIKELY_THRESHOLD = 0.75
DEFAULT_COOLDOWN = 120
DEFAULT_UNKNOWN_DELAY = 6
DEFAULT_UNKNOWN_CAMERAS = ""
DEFAULT_ANNOUNCE_UNKNOWN_VEHICLES = False
DEFAULT_PRESENCE_MINUTES = 10

EVENT_VISITOR = "stocker_vision_visitor"
EVENT_VEHICLE = "stocker_vision_vehicle"

SIGNAL_SIGHTING = f"{DOMAIN}_sighting"
SIGNAL_NEW_SUBJECT = f"{DOMAIN}_new_subject"

STORAGE_KEY = f"{DOMAIN}.subjects"
STORAGE_VERSION = 1
