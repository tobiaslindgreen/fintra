"""Constants for Fintra."""

from datetime import timedelta

DOMAIN = "fintra"

CONF_CHILDREN = "children"
CONF_AVAILABLE_CHILDREN = "available_children"
CONF_HOST = "host"
CONF_INCLUDE_MESSAGES = "include_messages"

DEFAULT_INCLUDE_MESSAGES = True
DEFAULT_UPDATE_INTERVAL = timedelta(days=1)

PLAN_TYPE_CLASS = "class"
PLAN_TYPE_SFO = "sfo"

PLATFORMS = ["sensor"]
