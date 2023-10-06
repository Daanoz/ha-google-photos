"""Support for Google Photos Albums."""
from __future__ import annotations
import dateutil.parser

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_ALBUM_ID,
)
from .coordinator import Coordinator, CoordinatorManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Google Photos sensors."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator_manager: CoordinatorManager = entry_data.get("coordinator_manager")

    album_ids = entry.options[CONF_ALBUM_ID]
    entities = []
    for album_id in album_ids:
        coordinator = await coordinator_manager.get_coordinator(album_id)
        entities.append(GooglePhotosMediaCount(coordinator))
        entities.append(GooglePhotosFileName(coordinator))
        entities.append(GooglePhotosCreationTimestamp(coordinator))

    async_add_entities(
        entities,
        False,
    )


class GooglePhotosFileName(SensorEntity):
    """Sensor to display current filename"""

    coordinator: Coordinator
    _attr_has_entity_name = True
    _attr_icon = "mdi:text-short"

    def __init__(self, coordinator: Coordinator) -> None:
        """Initialize a sensor class."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = SensorEntityDescription(
            key="filename", name="Filename", icon=self._attr_icon
        )
        album_id = self.coordinator.album["id"]
        self._attr_device_info = self.coordinator.get_device_info()
        self._attr_unique_id = f"{album_id}-filename"

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._read_value()

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.current_media is not None
        )

    def _read_value(self) -> None:
        if self.coordinator.current_media is not None:
            self._attr_native_value = self.coordinator.current_media.get("filename")
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._read_value()


class GooglePhotosCreationTimestamp(SensorEntity):
    """Sensor to display the current creation timestamp"""

    coordinator: Coordinator
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar"

    def __init__(self, coordinator: Coordinator) -> None:
        """Initialize a sensor class."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = SensorEntityDescription(
            key="creation_timestamp",
            name="Creation timestamp",
            icon=self._attr_icon,
            device_class=SensorDeviceClass.TIMESTAMP,
        )
        album_id = self.coordinator.album["id"]
        self._attr_device_info = self.coordinator.get_device_info()
        self._attr_unique_id = f"{album_id}-creation-timestamp"

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._read_value()

    @property
    def should_poll(self) -> bool:
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.current_media is not None
        )

    def _read_value(self) -> None:
        val = None
        if self.coordinator.current_media is not None:
            metadata = self.coordinator.current_media.get("mediaMetadata")
            if metadata is not None:
                creation_time = metadata.get("creationTime")
                if creation_time is not None:
                    val = dateutil.parser.isoparse(creation_time)
        self._attr_native_value = val
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._read_value()


class GooglePhotosMediaCount(SensorEntity):
    """Sensor to display current media count"""

    coordinator: Coordinator
    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: Coordinator) -> None:
        """Initialize a sensor class."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = SensorEntityDescription(
            key="media_count", name="Media count", icon=self._attr_icon
        )
        album_id = self.coordinator.album["id"]
        self._attr_device_info = self.coordinator.get_device_info()
        self._attr_unique_id = f"{album_id}-mediacount"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_value = len(self.coordinator.album_contents.album_list)
        self._attr_extra_state_attributes = {
            "is_updating": self.coordinator.album_contents.is_building_list
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

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
        self._attr_native_value = len(self.coordinator.album_contents.album_list)
        self._attr_extra_state_attributes[
            "is_updating"
        ] = self.coordinator.album_contents.is_building_list
        self.async_write_ha_state()
