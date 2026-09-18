"""hikvision component."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import traceback
from homeassistant.util import slugify
from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT as BINARY_SENSOR_ENTITY_ID_FORMAT,
)
from homeassistant.components.switch import ENTITY_ID_FORMAT as SWITCH_ENTITY_ID_FORMAT
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DEFAULT_LEGACY_EVENT_PORT, DOMAIN
from .capabilities import HikvisionCapabilityDiscovery
from .hikvision_device import HikvisionDevice
from .isapi import ISAPIUnauthorizedError
from .legacy_http import HikvisionLegacyHttpListener
from .notifications import EventNotificationsView
from .services import setup_services

_LOGGER = logging.getLogger(__name__)

# This integration is configured exclusively through config entries. It still
# defines async_setup to register shared services and HTTP views.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.IMAGE,
]

type HikvisionConfigEntry = ConfigEntry[HikvisionDevice]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hikvision component."""

    setup_services(hass)
    hass.http.register_view(EventNotificationsView(hass))
    legacy_listener = HikvisionLegacyHttpListener(hass)
    try:
        await legacy_listener.async_start()
    except OSError as ex:
        _LOGGER.warning(
            "Cannot start Hikvision legacy event listener on port %s: %s",
            DEFAULT_LEGACY_EVENT_PORT,
            ex,
        )

    @callback
    def async_stop_legacy_listener(_event) -> None:
        hass.async_create_task(legacy_listener.async_stop())

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop_legacy_listener)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: HikvisionConfigEntry) -> bool:
    """Set up integration from a config entry."""
    device = HikvisionDevice(hass, entry)
    device.pending_initialization = True
    try:
        await device.get_hardware_info()
        device_info = device.hass_device_info()
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(config_entry_id=entry.entry_id, **device_info)
    except ISAPIUnauthorizedError as ex:
        raise ConfigEntryAuthFailed from ex
    except Exception as ex:  # pylint: disable=broad-except
        msg = f"Cannot initialize {DOMAIN} {device.host}. Error: {ex}\n"
        _LOGGER.error(msg + traceback.format_exc())
        raise ConfigEntryNotReady(msg) from ex

    entry.runtime_data = device

    try:
        device.capabilities_registry = await HikvisionCapabilityDiscovery().async_discover(
            device, device.system_capabilities
        )
    except Exception as ex:  # pylint: disable=broad-except
        _LOGGER.debug("Capability discovery failed for %s: %s", device.host, ex)
        device.capabilities_registry = None

    await device.init_coordinators()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    device.pending_initialization = False

    refresh_disabled_entities_in_registry(hass, device)

    return True


async def async_remove_config_entry_device(hass: HomeAssistant, config_entry, device_entry) -> bool:
    """Delete device if not entities."""
    if not device_entry.via_device_id:
        _LOGGER.error(
            "You cannot delete the NVR device via the device delete method.  Please remove the integration instead"
        )
        return False
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HikvisionConfigEntry) -> bool:
    """Unload a config entry."""

    # Unload a config entry
    unload_ok = all(
        await asyncio.gather(
            *[hass.config_entries.async_forward_entry_unload(entry, platform) for platform in PLATFORMS]
        )
    )

    # Reset alarm server after it has been set
    device = entry.runtime_data
    if device.control_alarm_server_host:
        with suppress(Exception):
            await device.set_alarm_server("http://0.0.0.0:80", "/")

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    # 1 -> 2: Config entry unique_id format changed
    if config_entry.version == 1:
        unique_id = config_entry.unique_id
        if isinstance(unique_id, list) and len(unique_id) == 1 and isinstance(unique_id[0], list):
            new_unique_id = unique_id[0][1]
            hass.config_entries.async_update_entry(
                config_entry,
                data={**config_entry.data},
                unique_id=new_unique_id,
            )

        config_entry.version = 2

    # 2 -> 3: Delete previous alaram server sensor entities
    if config_entry.version == 2:
        old_keys = ["protocoltype", "ipaddress", "portno", "url"]
        entity_registry = er.async_get(hass)
        for key in old_keys:
            entity_id = f"sensor.{slugify(config_entry.unique_id)}_alarm_server_{key}"
            entity = entity_registry.async_get(entity_id)
            if entity:
                entity_registry.async_remove(entity_id)

        hass.config_entries.async_update_entry(
            config_entry,
            version=3,
        )

    _LOGGER.debug(
        "Migration to version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )

    return True


def refresh_disabled_entities_in_registry(hass: HomeAssistant, device: HikvisionDevice):
    """Set disable state according to Notify Surveillance Center flag."""

    def update_entity(event, ENTITY_ID_FORMAT):
        entity_id = ENTITY_ID_FORMAT.format(event.unique_id)
        entity = entity_registry.async_get(entity_id)
        if not entity:
            return
        if entity.disabled != event.disabled:
            disabled_by = er.RegistryEntryDisabler.INTEGRATION if event.disabled else None
            entity_registry.async_update_entity(entity_id, disabled_by=disabled_by)

    entity_registry = er.async_get(hass)
    for camera in device.cameras:
        for event in camera.events_info:
            update_entity(event, SWITCH_ENTITY_ID_FORMAT)
            update_entity(event, BINARY_SENSOR_ENTITY_ID_FORMAT)

    for event in device.events_info:
        update_entity(event, SWITCH_ENTITY_ID_FORMAT)
        update_entity(event, BINARY_SENSOR_ENTITY_ID_FORMAT)
