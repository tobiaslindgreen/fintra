"""Tests for the Fintra config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.fintra.const import (
    CONF_CHILDREN,
    CONF_HOST,
    CONF_INCLUDE_MESSAGES,
    DOMAIN,
)
from custom_components.fintra.models import Child

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_user_can_select_discovered_children(hass: HomeAssistant) -> None:
    """Test credentials, discovery and child selection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    discovered = (
        Child("641", "Ellie", "Ellie 2.KL."),
        Child("712", "Vester", "Vester 0.KL."),
    )
    client = MagicMock()
    client.async_login = AsyncMock(return_value=discovered)
    with patch(
        "custom_components.fintra.config_flow.FintraConfigFlow._new_client",
        return_value=client,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "https://school.example/",
                CONF_USERNAME: "parent",
                CONF_PASSWORD: "secret",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "children"

    with patch(
        "custom_components.fintra.async_setup_entry", return_value=True
    ) as setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_CHILDREN: ["641:Ellie", "712:Vester"],
                CONF_INCLUDE_MESSAGES: True,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "school.example"
    assert result["data"][CONF_HOST] == "school.example"
    assert result["options"][CONF_CHILDREN] == ["641:Ellie", "712:Vester"]
    assert result["options"][CONF_INCLUDE_MESSAGES] is True
    setup_entry.assert_awaited_once()


async def test_user_must_select_a_child(hass: HomeAssistant) -> None:
    """Test that an empty child selection is rejected."""
    client = MagicMock()
    client.async_login = AsyncMock(
        return_value=(Child("641", "Ellie", "Ellie"),)
    )
    with patch(
        "custom_components.fintra.config_flow.FintraConfigFlow._new_client",
        return_value=client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "school.example",
                CONF_USERNAME: "parent",
                CONF_PASSWORD: "secret",
            },
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CHILDREN: [], CONF_INCLUDE_MESSAGES: True},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CHILDREN: "select_child"}
