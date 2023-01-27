"""Support for Google Photos Albums."""
from __future__ import annotations
import asyncio
from datetime import datetime
from typing import Dict, List
import random
import logging

import voluptuous as vol


import aiohttp
import async_timeout

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import DeviceInfo, EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import (
    async_get_clientsession,
)

from .api import AsyncConfigEntryAuth
from .api_types import Album, MediaItem, PhotosLibraryService

from .const import (
    CONF_INTERVAL,
    CONF_MODE,
    DOMAIN,
    INTERVAL_OPTION_NONE,
    INTERVAL_DEFAULT_OPTION,
    MANUFACTURER,
    MODE_DEFAULT_OPTION,
    MODE_OPTION_ALBUM_ORDER,
    MODE_OPTIONS,
    CONF_WRITEMETADATA,
    WRITEMETADATA_DEFAULT_OPTION,
)

SERVICE_NEXT_MEDIA = "next_media"
ATTR_MODE = "mode"
CAMERA_NEXT_MEDIA_SCHEMA = {vol.Optional(ATTR_MODE): vol.In(MODE_OPTIONS)}

CAMERA_TYPE = CameraEntityDescription(
    key="album_image", name="Album image", icon="mdi:image"
)

THIRTY_MINUTES = 60 * 30

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Google Photos camera."""
    auth: AsyncConfigEntryAuth = hass.data[DOMAIN][entry.entry_id]
    service = await auth.get_resource(hass)

    def _get_albums() -> List[Album]:
        result = service.albums().list(pageSize=50).execute()
        album_list = result["albums"]
        while "nextPageToken" in result and result["nextPageToken"] != "":
            result = (
                service.albums()
                .list(pageSize=50, pageToken=result["nextPageToken"])
                .execute()
            )
            album_list = album_list + result["albums"]
        return album_list

    albums = await hass.async_add_executor_job(_get_albums)

    def as_camera(album: Album):
        return GooglePhotosAlbumCamera(
            hass.data[DOMAIN][entry.entry_id], album, CAMERA_TYPE
        )

    entities = [
        GooglePhotosFavoritesCamera(hass.data[DOMAIN][entry.entry_id], CAMERA_TYPE)
    ] + list(map(as_camera, albums))
    if len(entities) > 0:
        entities[0].enabled_by_default()

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
    """Base class Google Photos Camera class."""

    _auth: AsyncConfigEntryAuth
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:image"

    _media_id: str | None = None
    _media_item: MediaItem | None = None
    _media_cache: Dict[str, bytes] = {}
    _media_timestamp = datetime.now()
    _is_loading_next = False

    _album_cache: List[MediaItem] | None = None
    _album_timestamp = None

    def __init__(
        self,
        auth: AsyncConfigEntryAuth,
        description: EntityDescription,
    ) -> None:
        """Initialize a Google Photos Base Camera class."""
        super().__init__()
        self._auth = auth
        self.entity_description = description
        self._attr_native_value = "Cover photo"
        self._attr_frame_interval = 10
        self._attr_is_on = True
        self._attr_is_recording = False
        self._attr_is_streaming = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, auth.oauth_session.config_entry.entry_id)},
            manufacturer=MANUFACTURER,
            name="Google Photos Library",
        )
        self._attr_should_poll = False
        self._attr_extra_state_attributes = {}

    def enabled_by_default(self) -> None:
        """Set camera as enabled by default."""
        self._attr_entity_registry_enabled_default = True

    async def next_media(self, mode=None):
        """Load the next media."""
        if self._is_loading_next:
            return
        self._is_loading_next = True

        try:
            mode = mode or self._get_config_option(CONF_MODE, MODE_DEFAULT_OPTION)
            service = await self._auth.get_resource(self.hass)
            current_media = self._media_id or ""

            def _get_media_random() -> MediaItem | None:
                media_list = self._get_album_media(service)
                if len(media_list) < 1:
                    return None
                return random.choice(media_list)

            def _get_media_sequence() -> MediaItem | None:
                media_list = self._get_album_media(service)
                if len(media_list) < 1:
                    return None
                current_index = -1
                for index, media in enumerate(media_list):
                    if media["id"] == current_media:
                        current_index = index
                        break
                current_index = current_index + 1
                current_index = current_index % len(media_list)
                return media_list[current_index]

            if mode == MODE_OPTION_ALBUM_ORDER:
                media_item = await self.hass.async_add_executor_job(_get_media_sequence)
            else:
                media_item = await self.hass.async_add_executor_job(_get_media_random)

            if media_item is not None:
                self._set_media(media_item)
            self._media_timestamp = datetime.now()
        finally:
            self._is_loading_next = False

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image response from the camera."""
        await self._check_for_next_media()

        if (self._media_id or "") == "":
            _LOGGER.error("No media selected for %s", self.name)
            return None

        size_str = "=w" + str(width or 2048) + "-h" + str(height or 1024)
        if size_str in self._media_cache:
            return self._media_cache[size_str]

        service = await self._auth.get_resource(self.hass)

        def _get_media_url() -> str:
            media_item_age = (datetime.now() - self._media_timestamp).total_seconds()
            if self._media_item is not None and media_item_age < THIRTY_MINUTES:
                return self._media_item["baseUrl"]
            self._media_item = (
                service.mediaItems().get(mediaItemId=self._media_id).execute()
            )
            return self._media_item["baseUrl"]

        media_url = await self.hass.async_add_executor_job(_get_media_url)
        _LOGGER.debug("Loading %s", media_url)
        websession = async_get_clientsession(self.hass)
        try:
            async with async_timeout.timeout(10):
                response = await websession.get(media_url + size_str)
                image = await response.read()
                self._media_cache[size_str] = image
                return image

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout getting camera image from %s", self.name)

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting new camera image from %s: %s", self.name, err)

        return None

    async def _check_for_next_media(self) -> None:
        selected_interval = self._get_config_option(
            CONF_INTERVAL, INTERVAL_DEFAULT_OPTION
        )
        if selected_interval == INTERVAL_OPTION_NONE:
            return
        interval = int(selected_interval)

        time_delta = (datetime.now() - self._media_timestamp).total_seconds()
        if time_delta > interval:
            await self.next_media()

    def _get_config_option(self, prop, default) -> ConfigEntry:
        """Get config option."""
        config = self.hass.config_entries.async_get_entry(
            self._auth.oauth_session.config_entry.entry_id
        )
        if config.options is not None and prop in config.options:
            return config.options[prop]
        return default

    def _set_media(self, media: MediaItem) -> None:
        """Set next media."""
        self._set_media_id(media["id"])
        self._media_item = media
        write_metadata = self._get_config_option(
            CONF_WRITEMETADATA, WRITEMETADATA_DEFAULT_OPTION
        )
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

    def _set_media_id(self, media_id) -> None:
        """Set next media id."""
        self._media_id = media_id
        self._media_cache = {}

    def _get_album_media(self, service: PhotosLibraryService) -> List[MediaItem] | None:
        if self._album_cache is not None:
            cache_delta = (datetime.now() - self._album_timestamp).total_seconds()
            if cache_delta < THIRTY_MINUTES:
                return self._album_cache

        media_list = self._get_album_media_list(service)
        if media_list is None:
            return None

        self._album_cache = media_list
        self._album_timestamp = datetime.now()
        return media_list

    def _get_album_media_list(
        self, service: PhotosLibraryService
    ) -> List[MediaItem] | None:
        raise NotImplementedError("To be implemented by subclass")




class GooglePhotosAlbumCamera(GooglePhotosBaseCamera):
    """Representation of a Google Photos Album camera."""

    album: Album

    def __init__(
        self,
        auth: AsyncConfigEntryAuth,
        album: Album,
        description: EntityDescription,
    ) -> None:
        """Initialize a Google Photos album."""
        super().__init__(auth, description)
        self.album = album
        self._attr_name = album["title"]
        self._attr_unique_id = album["id"]
        self._set_media_id(album["coverPhotoMediaItemId"])

    def _get_album_media_list(
        self, service: PhotosLibraryService
    ) -> List[MediaItem] | None:
        album_id = self.album["id"]

        result = (
            service.mediaItems()
            .search(body=dict(pageSize=100, albumId=album_id))
            .execute()
        )
        if not "mediaItems" in result:
            return None

        media_list = result["mediaItems"]
        while "nextPageToken" in result and result["nextPageToken"] != "":
            result = (
                service.mediaItems()
                .search(
                    body=dict(
                        pageSize=100,
                        albumId=album_id,
                        pageToken=result["nextPageToken"],
                    )
                )
                .execute()
            )
            media_list = media_list + result["mediaItems"]

        return media_list


class GooglePhotosFavoritesCamera(GooglePhotosBaseCamera):
    """Representation of a Google Photos Favorites camera."""

    def __init__(
        self,
        auth: AsyncConfigEntryAuth,
        description: EntityDescription,
    ) -> None:
        """Initialize a Google Photos album."""
        super().__init__(auth, description)
        self._attr_name = "Favorites"
        self._attr_unique_id = "library_favorites"

    async def async_added_to_hass(self) -> None:
        await self.next_media()

    def _get_album_media_list(
        self, service: PhotosLibraryService
    ) -> List[MediaItem] | None:
        filters = {"featureFilter": {"includedFeatures": ["FAVORITES"]}}
        result = (
            service.mediaItems()
            .search(body=dict(pageSize=100, filters=filters))
            .execute()
        )
        if not "mediaItems" in result:
            return None

        media_list = result["mediaItems"]
        while "nextPageToken" in result and result["nextPageToken"] != "":
            result = (
                service.mediaItems()
                .search(
                    body=dict(
                        pageSize=100,
                        filters=filters,
                        pageToken=result["nextPageToken"],
                    )
                )
                .execute()
            )
            media_list = media_list + result["mediaItems"]

        return media_list
