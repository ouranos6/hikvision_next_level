"""Platform for supplement light brightness number entities."""

from __future__ import annotations

from homeassistant.components.number import ENTITY_ID_FORMAT, NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from . import HikvisionConfigEntry
from .capabilities import CapabilityState, HikvisionCapabilities, NumericCapability
from .hikvision_device import HikvisionDevice
from .isapi.utils import deep_get


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HikvisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add supplement light brightness number entities."""

    device = entry.runtime_data
    caps_registry = getattr(device, "capabilities_registry", None)

    entities: list[NumberEntity] = []

    for camera in device.cameras:
        caps = caps_registry.for_channel(camera.id) if caps_registry else HikvisionCapabilities()

        light_caps = caps.light_brightness
        if light_caps.state is CapabilityState.SUPPORTED:
            if caps.ir_light is CapabilityState.SUPPORTED:
                entities.append(
                    SupplementLightBrightnessNumber(device, camera.id, light_caps, "ir")
                )
            if caps.white_light is CapabilityState.SUPPORTED:
                entities.append(
                    SupplementLightBrightnessNumber(device, camera.id, light_caps, "white")
                )

        for setting, capability in (
            ("sensitivity", caps.motion_sensitivity),
            ("start_delay", caps.motion_start_delay),
            ("end_delay", caps.motion_end_delay),
        ):
            if _has_complete_range(capability):
                entities.append(MotionDetectionNumber(device, camera.id, capability, setting))

    async_add_entities(entities)


def _has_complete_range(capability: NumericCapability) -> bool:
    """Create a number only when ISAPI supplied its complete range metadata."""
    return (
        capability.state is CapabilityState.SUPPORTED
        and capability.minimum is not None
        and capability.maximum is not None
        and capability.step is not None
    )


class SupplementLightBrightnessNumber(NumberEntity):
    """Brightness control for a camera's supplement light."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lightbulb-outline"

    def __init__(
        self,
        device: HikvisionDevice,
        camera_id: int,
        light_caps: NumericCapability,
        light_type: str,
    ) -> None:
        """Initialize."""
        self._device = device
        self._camera_id = camera_id
        self._light_type = light_type

        self._attr_unique_id = (
            f"{slugify(device.device_info.serial_no.lower())}_{camera_id}"
            f"_{light_type}_light_brightness"
        )
        self.entity_id = ENTITY_ID_FORMAT.format(self._attr_unique_id)
        self._attr_device_info = device.hass_device_info(camera_id)
        self._attr_translation_key = light_type + "__light_brightness"

        self._attr_native_min_value = light_caps.minimum or 0
        self._attr_native_max_value = light_caps.maximum or 100
        self._attr_native_step = light_caps.step or 1

        self._current_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Fetch current state when added."""
        await self._async_update_value()
        self.async_write_ha_state()

    async def _async_update_value(self) -> None:
        """Read current supplement light brightness from device."""
        try:
            data = await self._device.get_supplement_light(self._camera_id)
            raw = (
                deep_get(data, "SupplementLight.whiteLightBrightness")
                or deep_get(data, "SupplementLight.supplementLightBrightness")
                or deep_get(data, "SupplementLight.lightBrightness")
            )
            if raw is not None:
                self._current_value = float(raw)
        except Exception:
            self._current_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set supplement light brightness."""
        try:
            brightness = int(value)
            await self._device.set_supplement_light_brightness(self._camera_id, brightness)
            self._current_value = float(brightness)
            self.async_write_ha_state()
        except Exception as ex:
            self._device.handle_exception(
                ex, f"Cannot set supplement light brightness for channel {self._camera_id}"
            )

    @property
    def native_value(self) -> float | None:
        """Return the current brightness value."""
        return self._current_value


class MotionDetectionNumber(NumberEntity):
    """One capability-advertised numeric motion-detection setting."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:motion-sensor"

    _SETTING_METADATA = {
        "sensitivity": ("motion_sensitivity", "MotionDetection.MotionDetectionLayout.sensitivityLevel"),
        "start_delay": ("motion_start_delay", "MotionDetection.startTriggerTime"),
        "end_delay": ("motion_end_delay", "MotionDetection.endTriggerTime"),
    }

    def __init__(
        self,
        device: HikvisionDevice,
        camera_id: int,
        capability: NumericCapability,
        setting: str,
    ) -> None:
        """Initialize using the exact min/max/step advertised by ISAPI."""
        translation_key, self._value_path = self._SETTING_METADATA[setting]
        self._device = device
        self._camera_id = camera_id
        self._setting = setting
        self._attr_unique_id = (
            f"{slugify(device.device_info.serial_no.lower())}_{camera_id}_{translation_key}"
        )
        self.entity_id = ENTITY_ID_FORMAT.format(self._attr_unique_id)
        self._attr_device_info = device.hass_device_info(camera_id)
        self._attr_translation_key = translation_key
        self._attr_native_min_value = capability.minimum
        self._attr_native_max_value = capability.maximum
        self._attr_native_step = capability.step
        self._current_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Read the current setting when the entity is first added."""
        await self._async_update_value()
        self.async_write_ha_state()

    async def _async_update_value(self) -> None:
        """Read the current setting without exposing transport errors as state."""
        try:
            value = deep_get(await self._device.get_motion_detection(self._camera_id), self._value_path)
            self._current_value = float(value) if value is not None else None
        except Exception:
            self._current_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Write a value, then re-read it so UI state mirrors the device."""
        try:
            await self._device.set_motion_detection_number(self._camera_id, self._setting, value)
            await self._async_update_value()
            self.async_write_ha_state()
        except Exception as ex:
            self._device.handle_exception(
                ex, f"Cannot set motion {self._setting} for channel {self._camera_id}"
            )

    @property
    def native_value(self) -> float | None:
        """Return the last value read from ISAPI."""
        return self._current_value
