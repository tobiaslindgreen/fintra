"""Fintra integration for Home Assistant."""

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import FintraClient
from .const import CONF_HOST, PLATFORMS
from .coordinator import FintraCoordinator

type FintraConfigEntry = ConfigEntry[FintraCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: FintraConfigEntry) -> bool:
	"""Set up Fintra from a config entry."""
	session = async_create_clientsession(hass, cookie_jar=CookieJar())
	client = FintraClient(
		session,
		entry.data[CONF_HOST],
		entry.data[CONF_USERNAME],
		entry.data[CONF_PASSWORD],
	)
	coordinator = FintraCoordinator(hass, entry, client)
	await coordinator.async_config_entry_first_refresh()
	entry.runtime_data = coordinator
	entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
	await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
	return True


async def async_unload_entry(hass: HomeAssistant, entry: FintraConfigEntry) -> bool:
	"""Unload a Fintra config entry."""
	return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: FintraConfigEntry) -> None:
	"""Reload Fintra after options change."""
	await hass.config_entries.async_reload(entry.entry_id)

