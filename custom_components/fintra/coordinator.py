"""Data coordinator for Fintra."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import FintraAuthError, FintraClient, FintraError
from .const import (
    CONF_CHILDREN,
    CONF_INCLUDE_MESSAGES,
    DEFAULT_INCLUDE_MESSAGES,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .models import ChildData

_LOGGER = logging.getLogger(__name__)


class FintraCoordinator(DataUpdateCoordinator[dict[str, ChildData]]):
    """Coordinate one daily fetch for all Fintra sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FintraClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict[str, ChildData]:
        selected = set(
            self.entry.options.get(CONF_CHILDREN, self.entry.data.get(CONF_CHILDREN, []))
        )
        include_messages = self.entry.options.get(
            CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES
        )
        try:
            return await self.client.async_fetch_data(
                selected,
                today=dt_util.now().date(),
                include_messages=include_messages,
            )
        except FintraAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FintraError as err:
            raise UpdateFailed(str(err)) from err
