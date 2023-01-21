"""Config flow for Google Photos integration."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
import voluptuous as vol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .const import (
    DEFAULT_ACCESS,
    DOMAIN,
    CONF_MODE,
    MODE_OPTIONS,
    MODE_DEFAULT_OPTION,
    CONF_INTERVAL,
    INTERVAL_OPTIONS,
    INTERVAL_DEFAULT_OPTION,
    CONF_WRITEMETADATA,
    WRITEMETADATA_DEFAULT_OPTION
)


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Google Photos OAuth2 authentication."""

    DOMAIN = DOMAIN

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

        email = (await self.hass.async_add_executor_job(_get_profile))["email"]

        await self.async_set_unique_id(email)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=email, data=data)

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

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODE,
                    default=self.config_entry.options.get(
                        CONF_MODE, MODE_DEFAULT_OPTION
                    ),
                ): vol.In(MODE_OPTIONS),
                vol.Optional(
                    CONF_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_INTERVAL, INTERVAL_DEFAULT_OPTION
                    ),
                ): vol.In(INTERVAL_OPTIONS),
                vol.Optional(
                    CONF_WRITEMETADATA,
                    default=self.config_entry.options.get(
                        CONF_WRITEMETADATA, WRITEMETADATA_DEFAULT_OPTION
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
