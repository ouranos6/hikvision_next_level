"""Regression tests for config entry lifecycle and stable identities."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hikvision_next.const import DOMAIN
from custom_components.hikvision_next.events import HikvisionEventProcessor
from tests.conftest import TEST_HOST_IP


@pytest.mark.parametrize("init_integration", ["DS-7608NXI-I2"], indirect=True)
async def test_nvr_setup_unload_reload_preserves_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """A config entry reload must not duplicate or rename existing entities."""

    entry = init_integration
    entity_registry = er.async_get(hass)
    entity_ids_before = {
        registry_entry.entity_id
        for registry_entry in entity_registry.entities.values()
        if registry_entry.config_entry_id == entry.entry_id
    }
    unique_ids_before = {
        registry_entry.unique_id
        for registry_entry in entity_registry.entities.values()
        if registry_entry.config_entry_id == entry.entry_id
    }

    assert entity_ids_before
    assert len(entity_ids_before) == len(unique_ids_before)

    with patch.object(hass.http, "register_view") as register_view:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    register_view.assert_not_called()
    assert entry.state is ConfigEntryState.LOADED

    entity_ids_after = {
        registry_entry.entity_id
        for registry_entry in entity_registry.entities.values()
        if registry_entry.config_entry_id == entry.entry_id
    }
    unique_ids_after = {
        registry_entry.unique_id
        for registry_entry in entity_registry.entities.values()
        if registry_entry.config_entry_id == entry.entry_id
    }

    assert entity_ids_after == entity_ids_before
    assert unique_ids_after == unique_ids_before


async def test_event_hostname_resolution_uses_executor(hass: HomeAssistant) -> None:
    """Hostname matching must not synchronously block Home Assistant's event loop."""

    processor = HikvisionEventProcessor(hass)

    with patch.object(hass, "async_add_executor_job", new_callable=AsyncMock, return_value=TEST_HOST_IP) as resolve:
        assert await processor._async_get_ip("camera.local") == TEST_HOST_IP

    resolve.assert_awaited_once()
