from __future__ import annotations
import asyncio
from datetime import datetime

import logging
import random
from typing import Dict, List
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
from .api import AsyncConfigEntryAuth
from .api_types import MediaItem
from .const import (
    CONF_INTERVAL,
    CONF_MODE,
    DOMAIN,
    INTERVAL_DEFAULT_OPTION,
    INTERVAL_OPTION_NONE,
    MODE_DEFAULT_OPTION,
    MODE_OPTION_ALBUM_ORDER,
)

_LOGGER = logging.getLogger(__name__)
FIFTY_MINUTES = 60 * 50


class Coordinator(DataUpdateCoordinator):
    """Coordinates data retrieval and selection from Google Photos"""

    _auth: AsyncConfigEntryAuth
    _config: ConfigEntry
    _context: dict[str, str | int] = dict()
    album_list: List[MediaItem] = []
    current_media: MediaItem | None = None

    current_media_cache: Dict[str, bytes] = {}

    # Timestamop when these items where loaded
    album_list_timestamp: datetime | None = None
    # Media selection timestamp, when was this image selected to be shown, used to calculate when to move to the next one
    current_media_selected_timestamp = datetime.now()
    # Age of the media object, because the data links are only valid for 60 mins,this is used to check if a new instance needs to be retrieved
    current_media_data_timestamp = datetime.now()

    def __init__(
        self, hass: HomeAssistant, auth: AsyncConfigEntryAuth, config: ConfigEntry
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

    def set_context(self, context: dict[str, str | int]):
        """Set coordinator context"""
        self._context = context

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
        return self.current_media.get("id")

    async def set_current_media_with_id(self, media_id: str):
        """Sets current selected media using only the id"""
        try:
            service = await self._auth.get_resource(self.hass)
            self.set_current_media(
                service.mediaItems().get(mediaItemId=media_id).execute()
            )
        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting image from %s: %s", self._context, err)

    def set_current_media(self, media: MediaItem):
        """Sets current selected media"""
        self.current_media = media
        self.current_media_cache = {}
        self.current_media_data_timestamp = self.album_list_timestamp
        self.current_media_selected_timestamp = datetime.now()
        self.async_update_listeners()

    def refresh_current_image(self) -> bool:
        """Selects next image if interval has passed"""
        self.hass.async_add_job(self._refresh_album_list)
        selected_interval = self.get_config_option(
            CONF_INTERVAL, INTERVAL_DEFAULT_OPTION
        )
        if selected_interval == INTERVAL_OPTION_NONE:
            return False
        interval = int(selected_interval)

        time_delta = (
            datetime.now() - self.current_media_selected_timestamp
        ).total_seconds()
        if time_delta > interval or self.current_media is None:
            self.select_next()
            return True
        return False

    def select_next(self, mode=None):
        """Select next media based on config"""
        mode = mode or self.get_config_option(CONF_MODE, MODE_DEFAULT_OPTION)
        if mode == MODE_OPTION_ALBUM_ORDER:
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
        size_str = "=w" + str(width or 1024) + "-h" + str(height or 512)
        if size_str in self.current_media_cache:
            return self.current_media_cache[size_str]

        try:
            service = await self._auth.get_resource(self.hass)

            def _get_media_url() -> str:
                media_item_age = (
                    datetime.now() - self.current_media_data_timestamp
                ).total_seconds()
                if self.current_media is not None and media_item_age < FIFTY_MINUTES:
                    return self.current_media.get("baseUrl")
                self.current_media = (
                    service.mediaItems()
                    .get(mediaItemId=self.current_media_id())
                    .execute()
                )
                self.current_media_data_timestamp = datetime.now()
                return self.current_media.get("baseUrl")

            media_url = await self.hass.async_add_executor_job(_get_media_url)
            _LOGGER.debug("Loading %s", media_url)
            websession = async_get_clientsession(self.hass)

            async with async_timeout.timeout(10):
                response = await websession.get(media_url + size_str)
                image = await response.read()
                self.current_media_cache[size_str] = image
                return image

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout getting image from %s", self._context)

        except aiohttp.ClientError as err:
            _LOGGER.error("Error getting new image from %s: %s", self._context, err)

        return None

    async def update_data(self):
        """Check if media list or current image needs to be refreshed"""
        await self._refresh_album_list()

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
        if self.album_list_timestamp is not None:
            cache_delta = (datetime.now() - self.album_list_timestamp).total_seconds()
            if cache_delta < FIFTY_MINUTES:
                return False
        await self._get_album_list()
        return True

    async def _async_update_data(self):
        """Fetch album data"""
        try:
            async with async_timeout.timeout(30):
                await self.update_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
