"""Platform for supplement light mode select entities."""

from __future__ import annotations

from homeassistant.components.select import ENTITY_ID_FORMAT, SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from . import HikvisionConfigEntry
from .capabilities import CapabilityState, HikvisionCapabilities, SelectCapability
from .hikvision_device import HikvisionDevice
from .isapi.utils import deep_get


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add supplement light mode select entities."""

    device = entry.runtime_data
    caps_registry = getattr(device, "capabilities_registry", None)

    entities: list[SupplementLightModeSelect] = []

    for camera in device.cameras:
        caps = caps_registry.for_channel(camera.id) if caps_registry else HikvisionCapabilities()

        mode_cap: SelectCapability = caps.supplement_light_mode
        if mode_cap.state is CapabilityState.SUPPORTED and mode_cap.options:
            entities.append(SupplementLightModeSelect(device, camera.id, caps))

    async_add_entities(entities)


class SupplementLightModeSelect(SelectEntity):
    """Supplement light mode selector for a camera channel."""

    _attr_has_entity_name = True
    _attr_translation_key = "supplement_light_mode"
    _attr_icon = "mdi:lightbulb"

    def __init__(
        self,
        device: HikvisionDevice,
        camera_id: int,
        caps: HikvisionCapabilities,
    ) -> None:
        """Initialize."""
        self._device = device
        self._camera_id = camera_id
        self._attr_unique_id = (
            f"{slugify(device.device_info.serial_no.lower())}_{camera_id}_supplement_light_mode"
        )
        self.entity_id = ENTITY_ID_FORMAT.format(self._attr_unique_id)
        self._attr_device_info = device.hass_device_info(camera_id)

        self._attr_options = list(caps.supplement_light_mode.options)

        self._current_option: str | None = None

    async def async_added_to_hass(self) -> None:
        """Fetch current state when added."""
        await self._async_update_current_option()
        self.async_write_ha_state()

    async def _async_update_current_option(self) -> None:
        """Read current supplement light mode from device."""
        try:
            data = await self._device.get_image_channel(self._camera_id)
            self._current_option = deep_get(data, "ImageChannel.supplementLightMode")
        except Exception:
            self._current_option = None

    async def async_select_option(self, option: str) -> None:
        """Set supplement light mode."""
        try:
            await self._device.set_supplement_light_mode(self._camera_id, option)
            self._current_option = option
            self.async_write_ha_state()
        except Exception as ex:
            self._device.handle_exception(ex, f"Cannot set supplement light mode for channel {self._camera_id}")

    @property
    def current_option(self) -> str | None:
        """Return the current supplement light mode."""
        return self._current_option
