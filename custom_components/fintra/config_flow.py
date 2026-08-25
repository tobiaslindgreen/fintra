"""Config flow for Fintra."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from aiohttp import CookieJar
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    FintraAuthError,
    FintraClient,
    FintraConnectionError,
    normalize_host,
)
from .const import (
    CONF_AVAILABLE_CHILDREN,
    CONF_CHILDREN,
    CONF_HOST,
    CONF_INCLUDE_MESSAGES,
    DEFAULT_INCLUDE_MESSAGES,
    DOMAIN,
)
from .models import Child


class FintraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fintra."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient flow data."""
        self._credentials: dict[str, Any] = {}
        self._children: tuple[Child, ...] = ()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect school and credentials and discover children."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
                client = self._new_client(
                    host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
                self._children = await client.async_login()
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            except FintraAuthError:
                errors["base"] = "invalid_auth"
            except FintraConnectionError:
                errors["base"] = "cannot_connect"
            else:
                unique_id = f"{host}:{user_input[CONF_USERNAME].casefold()}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                self._credentials = {
                    CONF_HOST: host,
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_AVAILABLE_CHILDREN: [
                        asdict(child) for child in self._children
                    ],
                }
                return await self.async_step_children()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): selector.TextSelector(),
                vol.Required(CONF_USERNAME): selector.TextSelector(),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_children(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user select children and optional message enrichment."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_CHILDREN, [])
            if not selected:
                errors[CONF_CHILDREN] = "select_child"
            else:
                return self.async_create_entry(
                    title=self._credentials[CONF_HOST],
                    data={**self._credentials, CONF_CHILDREN: selected},
                    options={
                        CONF_CHILDREN: selected,
                        CONF_INCLUDE_MESSAGES: user_input[CONF_INCLUDE_MESSAGES],
                    },
                )

        schema = _children_schema(
            self._children,
            selected=[child.key for child in self._children],
            include_messages=DEFAULT_INCLUDE_MESSAGES,
        )
        return self.async_show_form(
            step_id="children", data_schema=schema, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and save a replacement password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                client = self._new_client(
                    entry.data[CONF_HOST],
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                await client.async_login()
            except FintraAuthError:
                errors["base"] = "invalid_auth"
            except FintraConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
        )

    def _new_client(self, host: str, username: str, password: str) -> FintraClient:
        session = async_create_clientsession(self.hass, cookie_jar=CookieJar())
        return FintraClient(session, host, username, password)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return FintraOptionsFlow()


class FintraOptionsFlow(OptionsFlow):
    """Allow child and message settings to be changed."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage Fintra options."""
        if user_input is not None:
            if not user_input.get(CONF_CHILDREN):
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(),
                    errors={CONF_CHILDREN: "select_child"},
                )
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self) -> vol.Schema:
        children = tuple(
            Child(**item)
            for item in self.config_entry.data.get(CONF_AVAILABLE_CHILDREN, [])
        )
        selected = self.config_entry.options.get(
            CONF_CHILDREN, self.config_entry.data.get(CONF_CHILDREN, [])
        )
        return _children_schema(
            children,
            selected=selected,
            include_messages=self.config_entry.options.get(
                CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES
            ),
        )


def _children_schema(
    children: tuple[Child, ...],
    *,
    selected: list[str],
    include_messages: bool,
) -> vol.Schema:
    options = [
        selector.SelectOptionDict(value=child.key, label=child.name)
        for child in children
    ]
    return vol.Schema(
        {
            vol.Required(CONF_CHILDREN, default=selected): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_INCLUDE_MESSAGES, default=include_messages
            ): selector.BooleanSelector(),
        }
    )
