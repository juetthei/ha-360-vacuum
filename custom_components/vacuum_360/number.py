from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Robot360Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(Robot360Volume(coord) for coord in coordinators.values())


class Robot360Volume(CoordinatorEntity[Robot360Coordinator], NumberEntity):
    """Lautstärke in %; das Gerät meldet und erwartet Stufen 0–10 (App: 10 % = vol 1)."""

    _attr_has_entity_name = True
    _attr_name = "Lautstärke"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 10
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: Robot360Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.sn}_volume"

    @property
    def device_info(self) -> dict:
        return self.coordinator.device_info

    @property
    def native_value(self) -> int | None:
        vol = (self.coordinator.data or {}).get("vol")
        return vol * 10 if isinstance(vol, int) and 0 <= vol <= 10 else None

    async def async_set_native_value(self, value: float) -> None:
        level = round(value / 10)
        if not 0 <= level <= 10 or level * 10 != value:
            raise HomeAssistantError(f"Ungültige Lautstärke: {value}")
        await self.coordinator.api.set_volume(self.coordinator.sn, level)
        await self.coordinator.async_request_refresh()
