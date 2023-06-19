"""Coordinators to fetch data for all entities"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta

import logging
import math
import random
from typing import Dict, List, Tuple
import io
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

from .api import AsyncConfigEntryAuth
from .api_types import Album, MediaItem, MediaListItem, PhotosLibraryService
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

    album: Album = None
    album_id: str
    album_contents: AlbumDownloader
    current_media_primary: MediaDownloader | None = None
    current_media_secondary: MediaDownloader | None = None
    current_media_cache: Dict[str, bytes] = {}

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
            context = dict(filters=filters)
            self.album = Album(id=self.album_id, title="Favorites", isWriteable=False)
        else:
            context = dict(albumId=self.album_id)
        _LOGGER.debug("Creating new coordinator for: %s", context)
        self.album_contents = AlbumDownloader(hass, auth, context)

    @property
    def current_media(self) -> MediaItem | None:
        """Get current media item"""
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

    def current_media_id(self) -> str | None:
        """Id of current media"""
        media = self.current_media
        if media is None:
            return None
        return media.get("id")

    async def set_current_media_with_id(self, media_id: str | None):
        """Sets current selected media using only the id"""
        if media_id is None:
            return
        try:
            self.current_media_selected_timestamp = datetime.now()
            media = await self._get_media_by_id(media_id)
            self.current_media_primary = MediaDownloader(
                self.hass, self._auth, media, datetime.now()
            )
            self.current_media_secondary = None
            self.current_media_cache = {}
            self.async_update_listeners()
        except aiohttp.ClientError as err:
            self.current_media_selected_timestamp = 0
            _LOGGER.error(
                "Error getting image from %s: %s", self.album_contents.context, err
            )

    async def refresh_current_image(self) -> bool:
        """Selects next image if interval has passed"""
        interval = SETTING_INTERVAL_MAP.get(self.interval)
        if interval is None:
            return False
        if self.album_contents.requires_refresh:
            self.hass.async_add_job(self.async_request_refresh)

        time_delta = (
            datetime.now() - self.current_media_selected_timestamp
        ).total_seconds()
        if time_delta > interval or self.current_media is None:
            await self.select_next()
            return True
        return False

    async def select_next(self, mode=None):
        """Select next media based on config"""
        mode = mode or self.image_selection_mode
        if mode.lower() == SETTING_IMAGESELECTION_MODE_ALBUM_ORDER.lower():
            await self._select_sequential_media()
        else:
            await self._select_random_media()

    async def _select_random_media(self):
        """Selects a random media item from the list"""
        media_list = self.album_contents.photo_media_list()
        if len(media_list) > 1:
            item = random.choice(media_list)
            await self.set_current_media_with_id(item.get("id"))

    async def _select_sequential_media(self):
        """Finds the current photo in the list, and moves to the next"""
        media_list = self.album_contents.photo_media_list()
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
        item = media_list[current_index]
        await self.set_current_media_with_id(item.get("id"))

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
                self.album_contents.photo_media_list(),
            )
            secondary_media = random.choice(list(similar_orientation_images))
            if secondary_media is None:
                return None
            self.current_media_secondary = MediaDownloader(
                self.hass,
                self._auth,
                await self._get_media_by_id(secondary_media.get("id")),
                datetime.now(),
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

    async def _get_media_by_id(self, media_id: str | None) -> MediaItem:
        service = await self._auth.get_resource(self.hass)

        def _get_media_item() -> MediaItem:
            return service.mediaItems().get(mediaItemId=media_id).execute()

        return await self.hass.async_add_executor_job(_get_media_item)

    async def update_data(self):
        """Check if media list or current image needs to be refreshed"""
        await self.album_contents.refresh_album_list()
        self.update_interval = self.album_contents.update_interval

        if self.current_media is None and self.album is not None:
            if self.album.get("coverPhotoMediaItemId") is None:
                await self.select_next(None)
            else:
                await self.set_current_media_with_id(
                    self.album.get("coverPhotoMediaItemId")
                )

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


class AlbumDownloader:
    """Utility class for downloading the album contents"""

    _auth: AsyncConfigEntryAuth
    _hass: HomeAssistant
    _items_per_page = 100
    _content_refresh_interval = timedelta(hours=0, minutes=15)
    _loading = False
    _last_page_token = None
    _current_page_offset = 0

    album_list: List[MediaListItem] = []
    context: dict[str, str | int]
    update_interval: timedelta | None

    # Timestamp when these items where loaded
    album_list_timestamp = datetime.fromtimestamp(0)

    def __init__(
        self,
        hass: HomeAssistant,
        auth: AsyncConfigEntryAuth,
        context: dict[str, str | int],
    ) -> None:
        self._hass = hass
        self._auth = auth
        self.context = context

    async def _get_album_list(self):
        """This function will incrementally load the media list to avoid overloading the google servers. To avoid the media list being emptied every refresh interval, contents are replaced in place."""
        try:
            if self._loading:
                return
            self._loading = True

            # Limit the amount of items that are requested on each load so we don't bash the servers to much
            loop_limit = 300

            if self._last_page_token is None:
                # If the token is None, we are building the media list from scratch
                self._current_page_offset = 0
                # First request, only load the first 100 to speed up integration load times
                loop_limit = 100

            service = await self._auth.get_resource(self._hass)
            search_query = self.context.copy()
            fields = (
                "mediaItems(id,mediaMetadata(width,height,photo,video)),nextPageToken"
            )
            search_query["pageSize"] = self._items_per_page

            def sync_get_album_list() -> List[MediaListItem]:
                current_size = 0
                while current_size < loop_limit:
                    search_query["pageToken"] = self._last_page_token
                    result = (
                        service.mediaItems()
                        .search(body=search_query, fields=fields)
                        .execute()
                    )
                    if not "mediaItems" in result:
                        return

                    self._last_page_token = result.get("nextPageToken")
                    result_count = len(result.get("mediaItems"))
                    # Overwrite array slice with new items
                    self.album_list[
                        self._current_page_offset : (
                            self._current_page_offset + result_count
                        )
                    ] = result.get("mediaItems")
                    self._current_page_offset += result_count
                    current_size += result_count
                    if self._last_page_token is None:
                        break

            await self._hass.async_add_executor_job(sync_get_album_list)

            if self._last_page_token is None:
                # No token in last result, we are done loading!
                self.album_list_timestamp = datetime.now()
                self.update_interval = None
                self.album_list = self.album_list[0 : self._current_page_offset]
            else:
                self.update_interval = timedelta(seconds=30)

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting media list from %s: %s", self.context, err)

        finally:
            self._loading = False

    async def refresh_album_list(self) -> bool:
        """Check if content requires refresh"""
        if not self.requires_refresh:
            self.update_interval = None
            return False
        await self._get_album_list()
        return True

    def photo_media_list(self) -> List[MediaListItem]:
        """Get photos from media list"""
        return list(
            filter(
                lambda m: (m.get("mediaMetadata") or {}).get("photo") is not None,
                self.album_list,
            )
        )

    def video_media_list(self) -> List[MediaListItem]:
        """Get videos from media list"""
        return list(
            filter(
                lambda m: (m.get("mediaMetadata") or {}).get("video") is not None,
                self.album_list,
            )
        )

    @property
    def requires_refresh(self) -> bool:
        """Does the content require a refresh"""
        cache_delta = datetime.now() - self.album_list_timestamp
        return cache_delta > self._content_refresh_interval

    @property
    def is_building_list(self) -> bool:
        """Is the media list still being downloaded"""
        return self._last_page_token is not None


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
            media_url += size_str
            _LOGGER.debug("Loading %s", media_url)
            websession = async_get_clientsession(self.hass)

            async with async_timeout.timeout(10):
                response = await websession.get(media_url)
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
