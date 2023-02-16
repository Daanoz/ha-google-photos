"""Support for Google Photos Albums."""
from __future__ import annotations
from typing import List
import logging

import voluptuous as vol

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import AsyncConfigEntryAuth
from .api_types import Album
from .const import (
    DOMAIN,
    MANUFACTURER,
    MODE_OPTIONS,
    CONF_WRITEMETADATA,
    WRITEMETADATA_DEFAULT_OPTION,
    CONF_ALBUM_ID,
    CONF_ALBUM_ID_FAVORITES,
)
from .coordinator import Coordinator

SERVICE_NEXT_MEDIA = "next_media"
ATTR_MODE = "mode"
CAMERA_NEXT_MEDIA_SCHEMA = {vol.Optional(ATTR_MODE): vol.In(MODE_OPTIONS)}

CAMERA_TYPE = CameraEntityDescription(
    key="album_image", name="Album image", icon="mdi:image"
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Google Photos camera."""
    auth: AsyncConfigEntryAuth = hass.data[DOMAIN][entry.entry_id]
    service = await auth.get_resource(hass)
    album_ids = entry.options[CONF_ALBUM_ID]

    def _get_albums() -> List[GooglePhotosBaseCamera]:
        album_list = []
        for album_id in album_ids:
            coordinator = Coordinator(hass, auth, entry)
            if album_id == CONF_ALBUM_ID_FAVORITES:
                album_list.append(
                    GooglePhotosFavoritesCamera(entry.entry_id, coordinator)
                )
            else:
                album = service.albums().get(albumId=album_id).execute()
                album_list.append(
                    GooglePhotosAlbumCamera(entry.entry_id, coordinator, album)
                )
        return album_list

    entities = await hass.async_add_executor_job(_get_albums)

    for entity in entities:
        await entity.coordinator.async_config_entry_first_refresh()

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_NEXT_MEDIA,
        CAMERA_NEXT_MEDIA_SCHEMA,
        "next_media",
    )

    async_add_entities(
        entities,
        False,
    )


class GooglePhotosBaseCamera(Camera):
    """Base class Google Photos Camera class. Implements methods from CoordinatorEntity"""

    coordinator: Coordinator
    coordinator_contxt: dict[str, str | int]
    _attr_has_entity_name = True
    _attr_icon = "mdi:image"

    def __init__(
        self, coordinator: Coordinator, album_context: dict[str, str | int]
    ) -> None:
        """Initialize a Google Photos Base Camera class."""
        super().__init__()
        coordinator.set_context(album_context)
        self.coordinator = coordinator
        self.coordinator_context = album_context
        self.entity_description = CAMERA_TYPE
        self._attr_native_value = "Cover photo"
        self._attr_frame_interval = 10
        self._attr_is_on = True
        self._attr_is_recording = False
        self._attr_is_streaming = False
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(
                self._handle_coordinator_update, self.coordinator_context
            )
        )

    async def async_update(self) -> None:
        """Update the entity.

        Only used by the generic entity update service.
        """
        # Ignore manual update requests if the entity is disabled
        if not self.enabled:
            return

        await self.coordinator.async_request_refresh()

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        write_metadata = self.coordinator.get_config_option(
            CONF_WRITEMETADATA, WRITEMETADATA_DEFAULT_OPTION
        )
        media = self.coordinator.current_media
        if write_metadata:
            self._attr_extra_state_attributes["media_filename"] = (
                media.get("filename") or ""
            )
            self._attr_extra_state_attributes["media_metadata"] = (
                media.get("mediaMetadata") or {}
            )
            self._attr_extra_state_attributes["media_contributor_info"] = (
                media.get("contributorInfo") or {}
            )
            self.async_write_ha_state()

    def next_media(self, mode=None):
        """Load the next media."""
        self.coordinator.select_next(mode)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image response from the camera."""
        self.coordinator.refresh_current_image()
        if self.coordinator.current_media is None:
            _LOGGER.warning("No media selected for %s", self.name)
            return None
        return await self.coordinator.get_media_data(width, height)


class GooglePhotosAlbumCamera(GooglePhotosBaseCamera):
    """Representation of a Google Photos Album camera."""

    album: Album

    def __init__(self, entry_id: str, coordinator: Coordinator, album: Album) -> None:
        """Initialize a Google Photos album."""
        super().__init__(coordinator, dict(albumId=album["id"]))
        self.album = album
        self._attr_name = album["title"]
        self._attr_unique_id = album["id"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id, album["id"])},
            manufacturer=MANUFACTURER,
            name="Google Photos - " + album["title"],
            configuration_url=album["productUrl"],
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.coordinator.set_current_media_with_id(
            self.album["coverPhotoMediaItemId"]
        )


class GooglePhotosFavoritesCamera(GooglePhotosBaseCamera):
    """Representation of a Google Photos Favorites camera."""

    def __init__(
        self,
        entry_id: str,
        coordinator: Coordinator,
    ) -> None:
        """Initialize a Google Photos album."""
        filters = {"featureFilter": {"includedFeatures": ["FAVORITES"]}}
        super().__init__(coordinator, dict(filters=filters))
        self._attr_name = "Favorites"
        self._attr_unique_id = "library_favorites"
        self._attr_device_info = DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    entry_id,
                    CONF_ALBUM_ID_FAVORITES,
                )
            },
            manufacturer=MANUFACTURER,
            name="Google Photos - Favorites",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.next_media()
