"""Image entities with camera snapshots."""

from datetime import datetime
import logging

import voluptuous as vol

from homeassistant.components.camera import Camera
from homeassistant.components.image import ENTITY_ID_FORMAT, ImageEntity
from homeassistant.const import ATTR_ENTITY_ID, CONF_FILENAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import HikvisionConfigEntry
from .const import ACTION_UPDATE_SNAPSHOT
from .events import event_image_signal
from .hikvision_device import HikvisionDevice
from .isapi import AnalogCamera, CameraStreamInfo, IPCamera

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: HikvisionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add images with snapshots."""

    device = entry.runtime_data

    entities = []
    for camera in device.cameras:
        for stream in camera.streams:
            if stream.type_id == 1:
                entities.append(SnapshotFile(hass, device, camera, stream))
        if camera.events_info:
            entities.append(LastEventImage(hass, device, camera))

    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        ACTION_UPDATE_SNAPSHOT,
        {vol.Required(CONF_FILENAME): cv.template},
        "update_snapshot_filename",
    )


class SnapshotFile(ImageEntity):
    """An entity for displaying snapshot files."""

    _attr_has_entity_name = True
    file_path = None

    def __init__(
        self,
        hass: HomeAssistant,
        device: HikvisionDevice,
        camera: Camera,
        stream_info: CameraStreamInfo,
    ) -> None:
        """Initialize the snapshot file."""

        ImageEntity.__init__(self, hass)

        self._attr_unique_id = slugify(f"{device.device_info.serial_no.lower()}_{stream_info.id}_snapshot")
        self.entity_id = ENTITY_ID_FORMAT.format(self.unique_id)
        self._attr_translation_key = "snapshot"
        self._attr_translation_placeholders = {"camera": camera.name}

    def image(self) -> bytes | None:
        """Return bytes of image."""
        try:
            if self.file_path:
                with open(self.file_path, "rb") as file:
                    return file.read()
        except FileNotFoundError:
            _LOGGER.warning(
                "Could not read camera %s image from file: %s",
                self.name,
                self.file_path,
            )
        return None

    async def update_snapshot_filename(
        self,
        filename: Template,
    ) -> None:
        """Update the file_path."""
        self.file_path = filename.async_render(variables={ATTR_ENTITY_ID: self.entity_id})
        self._attr_image_last_updated = datetime.now()
        self.schedule_update_ha_state()


class LastEventImage(ImageEntity):
    """Expose the latest JPEG attached to an event for one camera."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_event"

    def __init__(
        self,
        hass: HomeAssistant,
        device: HikvisionDevice,
        camera: AnalogCamera | IPCamera,
    ) -> None:
        """Initialize an in-memory event image entity."""
        ImageEntity.__init__(self, hass)
        self._device = device
        self._camera_id = camera.id
        self._attr_unique_id = slugify(
            f"{device.device_info.serial_no.lower()}_{camera.id}_last_event"
        )
        self._attr_device_info = device.hass_device_info(camera.id)

    async def async_added_to_hass(self) -> None:
        """Subscribe to image updates for this camera only."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                event_image_signal(self._device.device_info.serial_no, self._camera_id),
                self._handle_event_image,
            )
        )

    def _handle_event_image(self) -> None:
        """Publish an updated timestamp after a new JPEG is stored."""
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    def image(self) -> bytes | None:
        """Return the in-memory JPEG without any snapshot request or disk I/O."""
        return self._device.get_last_event_image(self._camera_id)
