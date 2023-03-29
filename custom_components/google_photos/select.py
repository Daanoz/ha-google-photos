"""Support for Google Photos Albums."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    CONF_ALBUM_ID,
    SETTING_CROP_MODE_DEFAULT_OPTION,
    SETTING_CROP_MODE_OPTIONS,
    SETTING_IMAGESELECTION_MODE_DEFAULT_OPTION,
    SETTING_IMAGESELECTION_MODE_OPTIONS,
    SETTING_INTERVAL_DEFAULT_OPTION,
    SETTING_INTERVAL_OPTIONS,
)
from .coordinator import Coordinator, CoordinatorManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Google Photos selections."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator_manager: CoordinatorManager = entry_data.get("coordinator_manager")

    album_ids = entry.options[CONF_ALBUM_ID]
    entities = []
    for album_id in album_ids:
        coordinator = await coordinator_manager.get_coordinator(album_id)
        entities.append(GooglePhotosSelectCropMode(coordinator))
        entities.append(GooglePhotosSelectImageSelectionMode(coordinator))
        entities.append(GooglePhotosSelectInterval(coordinator))

    async_add_entities(
        entities,
        False,
    )


class GooglePhotosSelectCropMode(SelectEntity, RestoreEntity):
    """Selection of crop mode"""

    coordinator: Coordinator
    _attr_has_entity_name = True
    _attr_icon = "mdi:crop"

    def __init__(self, coordinator: Coordinator) -> None:
        """Initialize a sensor class."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = SelectEntityDescription(
            key="crop_mode",
            name="Crop mode",
            icon=self._attr_icon,
            entity_category=EntityCategory.CONFIG,
            options=SETTING_CROP_MODE_OPTIONS,
        )
        album_id = self.coordinator.album["id"]
        self._attr_device_info = self.coordinator.get_device_info()
        self._attr_unique_id = f"{album_id}-crop-mode"

    @property
    def should_poll(self) -> bool:
        """No need to poll."""
        return False

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        return self.coordinator.crop_mode

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option is not self.coordinator.crop_mode:
            self.coordinator.set_crop_mode(option)
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if not state or state.state not in SETTING_CROP_MODE_OPTIONS:
            self.coordinator.set_crop_mode(SETTING_CROP_MODE_DEFAULT_OPTION)
        else:
            self.coordinator.set_crop_mode(state.state)
        self.async_write_ha_state()


class GooglePhotosSelectImageSelectionMode(SelectEntity, RestoreEntity):
    """Selection of image selection mode"""

    coordinator: Coordinator
    _attr_has_entity_name = True
    _attr_icon = "mdi:page-next-outline"

    def __init__(self, coordinator: Coordinator) -> None:
        """Initialize a sensor class."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = SelectEntityDescription(
            key="image_selection_mode",
            name="Image selection mode",
            icon=self._attr_icon,
            entity_category=EntityCategory.CONFIG,
            options=SETTING_IMAGESELECTION_MODE_OPTIONS,
        )
        album_id = self.coordinator.album["id"]
        self._attr_device_info = self.coordinator.get_device_info()
        self._attr_unique_id = f"{album_id}-image-selection-mode"

    @property
    def should_poll(self) -> bool:
        """No need to poll."""
        return False

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        return self.coordinator.image_selection_mode

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option is not self.coordinator.image_selection_mode:
            self.coordinator.set_image_selection_mode(option)
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if not state or state.state not in SETTING_IMAGESELECTION_MODE_OPTIONS:
            self.coordinator.set_image_selection_mode(
                SETTING_IMAGESELECTION_MODE_DEFAULT_OPTION
            )
        else:
            self.coordinator.set_image_selection_mode(state.state)
        self.async_write_ha_state()


class GooglePhotosSelectInterval(SelectEntity, RestoreEntity):
    """Selection of image update interval"""

    coordinator: Coordinator
    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-cog"

    def __init__(self, coordinator: Coordinator) -> None:
        """Initialize a sensor class."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = SelectEntityDescription(
            key="update_interval",
            name="Update interval",
            icon=self._attr_icon,
            entity_category=EntityCategory.CONFIG,
            options=SETTING_INTERVAL_OPTIONS,
        )
        album_id = self.coordinator.album["id"]
        self._attr_device_info = self.coordinator.get_device_info()
        self._attr_unique_id = f"{album_id}-interval"

    @property
    def should_poll(self) -> bool:
        """No need to poll."""
        return False

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        return self.coordinator.interval

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option is not self.coordinator.interval:
            self.coordinator.set_interval(option)
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if not state or state.state not in SETTING_INTERVAL_OPTIONS:
            self.coordinator.set_interval(SETTING_INTERVAL_DEFAULT_OPTION)
        else:
            self.coordinator.set_interval(state.state)
        self.async_write_ha_state()
