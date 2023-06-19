"""Config flow for Google Photos integration."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, List
import voluptuous as vol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError as GoogleApiError

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .api_types import PhotosLibraryService, Album
from .const import (
    DEFAULT_ACCESS,
    DOMAIN,
    CONF_WRITEMETADATA,
    WRITEMETADATA_DEFAULT_OPTION,
    CONF_ALBUM_ID,
    CONF_ALBUM_ID_FAVORITES,
)


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Google Photos OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 2

    reauth_entry: ConfigEntry | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {
            "scope": " ".join(DEFAULT_ACCESS),
            # Add params to ensure we get back a refresh token
            "access_type": "offline",
            "prompt": "consent",
        }

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauth dialog."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create an entry for the flow, or update existing entry."""
        if self.reauth_entry:
            self.hass.config_entries.async_update_entry(self.reauth_entry, data=data)
            await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        credentials = Credentials(data[CONF_TOKEN][CONF_ACCESS_TOKEN])

        def _get_profile() -> dict[str, Any]:
            """Get profile from inside the executor."""
            lib = build("oauth2", "v2", credentials=credentials)
            userinfo = lib.userinfo().get().execute()  # pylint: disable=no-member
            return userinfo

        def _check_photoslibrary_access() -> PhotosLibraryService:
            lib = build(
                "photoslibrary",
                "v1",
                credentials=credentials,
                static_discovery=False,
            )
            albums = (
                lib.albums().list(pageSize=1).execute()  # pylint: disable=no-member
            )
            return albums

        try:
            (await self.hass.async_add_executor_job(_check_photoslibrary_access))
            email = (await self.hass.async_add_executor_job(_get_profile))["email"]
        except GoogleApiError as ex:
            return self.async_abort(
                reason="access_error", description_placeholders={"reason": ex.reason}
            )

        await self.async_set_unique_id(email)
        self._abort_if_unique_id_configured()

        options = dict()
        options[CONF_ALBUM_ID] = [CONF_ALBUM_ID_FAVORITES]
        return self.async_create_entry(title=email, data=data, options=options)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for google photos."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return logging.getLogger(__name__)

    async def _get_albumselect_schema(self) -> vol.Schema:
        """Return album selection form"""

        credentials = Credentials(self.config_entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN])

        def get_photoslibrary() -> PhotosLibraryService:
            return build(
                "photoslibrary",
                "v1",
                credentials=credentials,
                static_discovery=False,
            )

        def get_albums() -> List[Album]:
            service: PhotosLibraryService = get_photoslibrary()
            albums = service.albums()  # pylint: disable=no-member
            fields = "albums(id,title,mediaItemsCount),nextPageToken"
            request = albums.list(pageSize=50, fields=fields)
            album_list = []
            while request is not None:
                result = request.execute()
                album_list = album_list + result.get("albums", [])
                request = albums.list_next(request, result)

            sharedAlbums = service.sharedAlbums()  # pylint: disable=no-member
            fields = "sharedAlbums(id,title,mediaItemsCount),nextPageToken"
            request = sharedAlbums.list(pageSize=50, fields=fields)
            while request is not None:
                result = request.execute()
                album_list = album_list + result.get("sharedAlbums", [])
                request = sharedAlbums.list_next(request, result)
            return list(filter(lambda a: ("id" in a and "title" in a), album_list))

        albums = await self.hass.async_add_executor_job(get_albums)
        album_selection = dict({CONF_ALBUM_ID_FAVORITES: "Favorites"})
        for album in albums:
            album_selection[album.get("id")] = "{0} ({1} items)".format(
                album.get("title"), album.get("mediaItemsCount", "?")
            )

        return vol.Schema(
            {
                vol.Required(CONF_ALBUM_ID): vol.In(album_selection),
            }
        )

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["albumselect", "settings"],
            description_placeholders={
                "model": "Example model",
            },
        )

    async def async_step_albumselect(
        self, user_input: dict[str, Any] = None
    ) -> FlowResult:
        """Set the album used."""
        self.logger.debug(
            "async_albumselect_confirm called with user_input: %s", user_input
        )

        # user input was not provided.
        if user_input is None:
            data_schema = await self._get_albumselect_schema()
            return self.async_show_form(step_id="albumselect", data_schema=data_schema)

        album_id = user_input[CONF_ALBUM_ID]
        albums = self.config_entry.options.get(CONF_ALBUM_ID, []).copy()
        if album_id not in albums:
            albums.append(album_id)
        data = self.config_entry.options.copy()
        data.update({CONF_ALBUM_ID: albums})
        return self.async_create_entry(title="", data=data)

    async def async_step_settings(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            data = self.config_entry.options.copy()
            data.update(user_input)
            return self.async_create_entry(title="", data=data)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_WRITEMETADATA,
                    default=self.config_entry.options.get(
                        CONF_WRITEMETADATA, WRITEMETADATA_DEFAULT_OPTION
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="settings", data_schema=data_schema)
