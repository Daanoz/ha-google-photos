"""Coordinators to fetch data for all entities"""
from __future__ import annotations
import asyncio
from datetime import datetime

import logging
import math
import random
from typing import Dict, List, Tuple
import aiohttp
import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.aiohttp_client import (
    async_get_clientsession,
)
from homeassistant.helpers.entity import DeviceInfo

from PIL import Image
import io

from .api import AsyncConfigEntryAuth
from .api_types import Album, MediaItem, PhotosLibraryService
from .const import (
    CONF_ALBUM_ID_FAVORITES,
    DOMAIN,
    MANUFACTURER,
    SETTING_CROP_MODE_COMBINED,
    SETTING_CROP_MODE_CROP,
    SETTING_CROP_MODE_DEFAULT_OPTION,
    SETTING_IMAGESELECTION_MODE_ALBUM_ORDER,
    SETTING_IMAGESELECTION_MODE_DEFAULT_OPTION,
    SETTING_INTERVAL_DEFAULT_OPTION,
    SETTING_INTERVAL_MAP,
)

_LOGGER = logging.getLogger(__name__)
FIFTY_MINUTES = 60 * 50


class CoordinatorManager:
    """Manages all coordinators used by integration (one per album)"""

    hass: HomeAssistant
    _config: ConfigEntry
    _auth: AsyncConfigEntryAuth
    coordinators: dict[str, Coordinator] = dict()
    coordinator_first_refresh: dict[str, asyncio.Task] = dict()

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigEntry,
        auth: AsyncConfigEntryAuth,
    ) -> None:
        self.hass = hass
        self._config = config
        self._auth = auth

    async def get_coordinator(self, album_id: str) -> Coordinator:
        """Get a unique coordinator for specific album_id"""
        if album_id in self.coordinators:
            await self.coordinator_first_refresh.get(album_id)
            return self.coordinators.get(album_id)
        self.coordinators[album_id] = Coordinator(
            self.hass, self._auth, self._config, album_id
        )
        first_refresh = asyncio.create_task(
            self.coordinators[album_id].async_config_entry_first_refresh()
        )
        self.coordinator_first_refresh[album_id] = first_refresh
        await first_refresh
        return self.coordinators[album_id]

    def remove_coordinator(self, album_id: str):
        """Remove coordinator instance"""
        if album_id not in self.coordinators:
            return
        self.coordinators.pop(album_id)
        self.coordinator_first_refresh.pop(album_id)


class Coordinator(DataUpdateCoordinator):
    """Coordinates data retrieval and selection from Google Photos"""

    _auth: AsyncConfigEntryAuth
    _config: ConfigEntry
    _context: dict[str, str | int] = dict()
    album: Album = None
    album_id: str
    album_list: List[MediaItem] = []
    current_media_primary: MediaDownloader | None = None
    current_media_secondary: MediaDownloader | None = None

    current_media_cache: Dict[str, bytes] = {}

    # Timestamop when these items where loaded
    album_list_timestamp = datetime.fromtimestamp(0)
    # Media selection timestamp, when was this image selected to be shown,
    # used to calculate when to move to the next one
    current_media_selected_timestamp = datetime.fromtimestamp(0)

    crop_mode = SETTING_CROP_MODE_DEFAULT_OPTION
    image_selection_mode = SETTING_IMAGESELECTION_MODE_DEFAULT_OPTION
    interval = SETTING_INTERVAL_DEFAULT_OPTION

    def __init__(
        self,
        hass: HomeAssistant,
        auth: AsyncConfigEntryAuth,
        config: ConfigEntry,
        album_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=None,
        )
        self._auth = auth
        self._config = config
        self.album_id = album_id

        if self.album_id == CONF_ALBUM_ID_FAVORITES:
            filters = {"featureFilter": {"includedFeatures": ["FAVORITES"]}}
            self.set_context(dict(filters=filters))
            self.album = Album(id=self.album_id, title="Favorites", isWriteable=False)
        else:
            self.set_context(dict(albumId=self.album_id))

    @property
    def current_media(self) -> MediaItem | None:
        if self.current_media_primary is None:
            return None
        return self.current_media_primary.media

    def get_device_info(self) -> DeviceInfo:
        """Fetches device info for coordinator instance"""
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    self._config.entry_id,
                    self.album_id,
                )
            },
            manufacturer=MANUFACTURER,
            name="Google Photos - " + self.album.get("title"),
            configuration_url=self.album.get("productUrl", None),
        )

    def set_context(self, context: dict[str, str | int]):
        """Set coordinator context"""
        self._context = context

    def set_crop_mode(self, crop_mode: str):
        """Set crop mode"""
        self.current_media_cache = {}
        self.crop_mode = crop_mode

    def set_image_selection_mode(self, image_selection_mode: str):
        """Set image selection mode"""
        self.image_selection_mode = image_selection_mode

    def set_interval(self, interval: str):
        """Set interval"""
        self.interval = interval

    def get_config_option(self, prop, default) -> ConfigEntry:
        """Get config option."""
        if self._config.options is not None and prop in self._config.options:
            return self._config.options[prop]
        return default

    def photo_media_list(self) -> List[MediaItem]:
        """Get photos from media list"""
        return list(
            filter(
                lambda m: (m.get("mediaMetadata") or {}).get("photo") is not None,
                self.album_list,
            )
        )

    def video_media_list(self) -> List[MediaItem]:
        """Get videos from media list"""
        return list(
            filter(
                lambda m: (m.get("mediaMetadata") or {}).get("video") is not None,
                self.album_list,
            )
        )

    def current_media_id(self) -> str | None:
        """Id of current media"""
        media = self.current_media
        if media is None:
            return None
        return media.get("id")

    async def set_current_media_with_id(self, media_id: str):
        """Sets current selected media using only the id"""
        try:
            service = await self._auth.get_resource(self.hass)

            def _get_media_item() -> MediaItem:
                return service.mediaItems().get(mediaItemId=media_id).execute()

            self.set_current_media(
                await self.hass.async_add_executor_job(_get_media_item)
            )
        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting image from %s: %s", self._context, err)

    def set_current_media(self, media: MediaItem):
        """Sets current selected media"""
        self.current_media_primary = MediaDownloader(
            self.hass, self._auth, media, self.album_list_timestamp
        )
        self.current_media_secondary = None
        self.current_media_cache = {}
        self.current_media_selected_timestamp = datetime.now()
        self.async_update_listeners()

    def refresh_current_image(self) -> bool:
        """Selects next image if interval has passed"""
        self.hass.async_add_job(self._refresh_album_list)
        interval = SETTING_INTERVAL_MAP.get(self.interval)
        if interval is None:
            return False

        time_delta = (
            datetime.now() - self.current_media_selected_timestamp
        ).total_seconds()
        if time_delta > interval or self.current_media is None:
            self.select_next()
            return True
        return False

    def select_next(self, mode=None):
        """Select next media based on config"""
        mode = mode or self.image_selection_mode
        if mode.lower() == SETTING_IMAGESELECTION_MODE_ALBUM_ORDER.lower():
            self.select_sequential_media()
        else:
            self.select_random_media()

    def select_random_media(self):
        """Selects a random media item from the list"""
        media_list = self.photo_media_list()
        if len(media_list) > 1:
            self.set_current_media(random.choice(media_list))

    def select_sequential_media(self):
        """Finds the current photo in the list, and moves to the next"""
        media_list = self.photo_media_list()
        if len(media_list) < 1:
            return
        current_index = -1
        current_media_id = self.current_media_id()
        for index, media in enumerate(media_list):
            if media.get("id") == current_media_id:
                current_index = index
                break
        current_index = current_index + 1
        current_index = current_index % len(media_list)
        self.set_current_media(media_list[current_index])

    async def get_media_data(self, width: int | None = None, height: int | None = None):
        """Get a binary image data for the current media"""
        width = width or 1024
        height = height or 512

        size_str = "=w" + str(width) + "-h" + str(height)
        if self.crop_mode in [SETTING_CROP_MODE_CROP, SETTING_CROP_MODE_COMBINED]:
            size_str += "-c"
        if size_str in self.current_media_cache:
            return self.current_media_cache[size_str]

        if self.crop_mode == SETTING_CROP_MODE_COMBINED:
            result = await self._get_combined_media_data(width, height)
            if result is not None:
                self.current_media_cache[size_str] = result
                return self.current_media_cache[size_str]

        self.current_media_cache[size_str] = await self.current_media_primary.download(
            size_str
        )
        return self.current_media_cache[size_str]

    async def _get_combined_media_data(self, width: int, height: int):
        """Get a binary image data for the current media"""
        requested_dimensions = (float(width), float(height))
        media_dimensions = self._get_media_dimensions()
        media_is_portrait = self._is_portrait(media_dimensions)
        if self._is_portrait(requested_dimensions) is media_is_portrait:
            # Requested orientation matches media orientation
            return None

        combined_image_dimensions = self._calculate_combined_image_dimensions(
            requested_dimensions, media_dimensions
        )
        cut_loss_single = self._calculate_cut_loss(
            requested_dimensions, media_dimensions
        )
        cut_loss_combined = self._calculate_cut_loss(
            combined_image_dimensions, media_dimensions
        )
        if cut_loss_single < cut_loss_combined:
            # Bigger part of the image would be lost with combined images
            return None

        if self.current_media_secondary is None:
            similar_orientation_images = filter(
                lambda m: (
                    self._is_portrait(self._get_media_dimensions(m))
                    is media_is_portrait
                )
                and (m.get("id") != self.current_media_id()),
                self.photo_media_list(),
            )
            secondary_media = random.choice(list(similar_orientation_images))
            if secondary_media is None:
                return None
            self.current_media_secondary = MediaDownloader(
                self.hass, self._auth, secondary_media, self.album_list_timestamp
            )

        size_str = (
            "=w"
            + str(math.ceil(combined_image_dimensions[0]))
            + "-h"
            + str(math.ceil(combined_image_dimensions[1]))
            + "-c"
        )
        images = await asyncio.gather(
            self.current_media_primary.download(size_str),
            self.current_media_secondary.download(size_str),
        )
        if images[0] is None or images[1] is None:
            return None

        with Image.new("RGB", (width, height), "white") as output:
            output.paste(Image.open(io.BytesIO(images[0])), (0, 0))
            if combined_image_dimensions[0] < requested_dimensions[0]:
                output.paste(
                    Image.open(io.BytesIO(images[1])),
                    (math.floor(combined_image_dimensions[0]), 0),
                )
            else:
                output.paste(
                    Image.open(io.BytesIO(images[1])),
                    (0, math.floor(combined_image_dimensions[1])),
                )
            with io.BytesIO() as result:
                output.save(result, "JPEG")
                return result.getvalue()

    async def update_data(self):
        """Check if media list or current image needs to be refreshed"""
        await self._refresh_album_list()

    def _is_portrait(self, dimensions: Tuple[float, float]) -> bool:
        """Returns if the given dimension represent a portrait media item"""
        return dimensions[0] < dimensions[1]

    def _calculate_combined_image_dimensions(
        self, target: Tuple[float, float], src: Tuple[float, float]
    ) -> Tuple[float, float]:
        multiplier_width = target[0] / src[0]
        multiplier_height = target[1] / src[1]
        if multiplier_height > multiplier_width:
            return (target[0], target[1] / 2)
        else:
            return (target[0] / 2, target[1])

    def _calculate_cut_loss(
        self, target: Tuple[float, float], src: Tuple[float, float]
    ) -> float:
        multiplier = max(target[0] / src[0], target[1] / src[1])
        return 1 - (
            (target[0] * target[1]) / ((src[0] * multiplier) * (src[1] * multiplier))
        )

    def _get_media_dimensions(
        self, media: MediaItem | None = None
    ) -> Tuple[float, float] | None:
        """Get the dimensions of the media item"""
        media = media or self.current_media
        if media is None:
            return None
        metadata = media.get("mediaMetadata")
        if metadata is None:
            return None
        width = metadata.get("width")
        height = metadata.get("height")
        if width is None or height is None:
            return None
        return (float(width), float(height))

    async def _get_album_list(self):
        try:
            service = await self._auth.get_resource(self.hass)
            search_query = self._context.copy()
            search_query["pageSize"] = 100

            def sync_get_album_list() -> List[MediaItem]:
                result = service.mediaItems().search(body=search_query).execute()
                if not "mediaItems" in result:
                    return []

                album_list = result["mediaItems"]
                while "nextPageToken" in result and result["nextPageToken"] != "":
                    search_query["pageToken"] = result["nextPageToken"]
                    result = service.mediaItems().search(body=search_query).execute()
                    album_list = album_list + result["mediaItems"]
                return album_list

            self.album_list = await self.hass.async_add_executor_job(
                sync_get_album_list
            )
            self.album_list_timestamp = datetime.now()
        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting media lise from %s: %s", self._context, err)

    async def _refresh_album_list(self) -> bool:
        cache_delta = (datetime.now() - self.album_list_timestamp).total_seconds()
        if cache_delta < FIFTY_MINUTES:
            return False
        await self._get_album_list()
        return True

    async def _async_update_data(self):
        """Fetch album data"""

        try:
            async with async_timeout.timeout(30):
                if self.album is None:
                    service = await self._auth.get_resource(self.hass)

                    def _get_album(album_id: str) -> Album:
                        return service.albums().get(albumId=album_id).execute()

                    self.album = await self.hass.async_add_executor_job(
                        _get_album, self.album_id
                    )
                await self.update_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err


class MediaDownloader:
    """Utility class for downloading media"""

    hass: HomeAssistant
    auth: AsyncConfigEntryAuth
    media: MediaItem
    media_timestamp: datetime

    def __init__(
        self,
        hass: HomeAssistant,
        auth: AsyncConfigEntryAuth,
        media: MediaItem,
        media_timestamp: datetime,
    ) -> None:
        self.hass = hass
        self.auth = auth
        self.media = media
        self.media_timestamp = media_timestamp

    async def download(self, size_str: str):
        """Get a binary image data"""
        try:
            service = await self.auth.get_resource(self.hass)

            media_url = await self.hass.async_add_executor_job(
                self._get_media_url, service
            )
            _LOGGER.debug("Loading %s", media_url)
            websession = async_get_clientsession(self.hass)

            async with async_timeout.timeout(10):
                response = await websession.get(media_url + size_str)
                return await response.read()

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout getting image: %s", self.media.get("id"))

        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Error getting new image from %s: %s", self.media.get("id"), err
            )

        return None

    def _get_media_url(self, service: PhotosLibraryService) -> str:
        media_item_age = (datetime.now() - self.media_timestamp).total_seconds()
        if media_item_age < FIFTY_MINUTES:
            return self.media.get("baseUrl")
        self.media = (
            service.mediaItems().get(mediaItemId=self.media.get("id")).execute()
        )
        self.media_timestamp = datetime.now()
        return self.media.get("baseUrl")
