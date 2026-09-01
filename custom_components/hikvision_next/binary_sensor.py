"""Platform for binary sensor integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from . import HikvisionConfigEntry
from .capabilities import CapabilityState, HikvisionCapabilities
from .const import EVENTS
from .hikvision_device import HikvisionDevice
from .isapi import EventInfo
from .isapi.const import EVENT_IO


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for hikvision events states."""

    device = entry.runtime_data

    entities = []

    # Video Events
    for camera in device.cameras:
        for event in camera.events_info:
            entities.append(EventBinarySensor(device, camera.id, event))

    # General Events
    for event in device.events_info:
        entities.append(EventBinarySensor(device, 0, event))

    # Person / Vehicle detection sensors
    caps_registry = getattr(device, "capabilities_registry", None)
    for camera in device.cameras:
        caps = caps_registry.for_channel(camera.id) if caps_registry else HikvisionCapabilities()
        has_target_events = any(
            event.id in ("fielddetection", "linedetection") for event in camera.events_info
        )
        if _should_create_target_entity(caps.human_filter, has_target_events):
            entities.append(TargetBinarySensor(device, camera.id, "person"))
        if _should_create_target_entity(caps.vehicle_filter, has_target_events):
            entities.append(TargetBinarySensor(device, camera.id, "vehicle"))

    async_add_entities(entities)


def _should_create_target_entity(state: CapabilityState, has_target_events: bool) -> bool:
    """Decide whether a person/vehicle sensor should be created for a channel."""
    if state is CapabilityState.SUPPORTED:
        return True
    if state is CapabilityState.UNSUPPORTED:
        return False
    return has_target_events


class EventBinarySensor(BinarySensorEntity):
    """Event detection sensor."""

    _attr_has_entity_name = True
    _attr_is_on = False

    def __init__(self, device: HikvisionDevice, device_id: int, event: EventInfo) -> None:
        """Initialize."""
        self.entity_id = ENTITY_ID_FORMAT.format(event.unique_id)
        self._attr_unique_id = self.entity_id
        self._attr_translation_key = event.id
        if event.id == EVENT_IO:
            self._attr_translation_placeholders = {"io_port_id": event.io_port_id}
        self._attr_device_class = EVENTS[event.id]["device_class"]
        self._attr_device_info = device.hass_device_info(device_id)
        self._attr_entity_registry_enabled_default = not event.disabled


class TargetBinarySensor(BinarySensorEntity):
    """Person or vehicle detection sensor updated from push events."""

    _attr_has_entity_name = True
    _attr_is_on = False
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        device: HikvisionDevice,
        camera_id: int,
        target_type: str,
    ) -> None:
        """Initialize."""
        serial_no = slugify(device.device_info.serial_no.lower())
        self._attr_unique_id = f"{serial_no}_{camera_id}_{target_type}"
        self._attr_translation_key = target_type
        self._attr_device_info = device.hass_device_info(camera_id)
