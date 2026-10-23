import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAP_GUARDS, DOMAIN
from .coordinator import Robot360Coordinator
from .map_guard import Robot360MapGuardCoordinator

_LOGGER = logging.getLogger(__name__)

# Feldnamen variieren je nach Firmware-Version, daher flexibles Parsing
# (gleiches Muster wie coordinator._extract_status).
_BATTERY_KEYS = ("elecReal", "elec", "battery", "batteryLevel", "power")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    sensors = [Robot360BatterySensor(coord) for coord in coordinators.values()]
    guards = entry.options.get(CONF_MAP_GUARDS, {})
    for coord in coordinators.values():
        if expected := guards.get(coord.sn):
            guard = Robot360MapGuardCoordinator(coord, expected)
            await guard.async_refresh()
            sensors.append(Robot360MapGuardSensor(guard))
    async_add_entities(sensors)


class Robot360MapGuardSensor(CoordinatorEntity[Robot360MapGuardCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Treppensperre"
    _attr_icon = "mdi:shield-home"

    def __init__(self, coordinator: Robot360MapGuardCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.robot.sn}_map_guard"

    @property
    def device_info(self) -> dict:
        return self.coordinator.robot.device_info

    @property
    def native_value(self) -> str:
        return self.coordinator.data or "check_failed"


class Robot360BatterySensor(CoordinatorEntity[Robot360Coordinator], SensorEntity):
    """Akkustand des Roboters.

    Bis HA 2026.8 lag der Wert als battery_level-Attribut an der Vacuum-Entity.
    HA 2026.9 hat Batterie vollständig aus VacuumEntityFeature und
    StateVacuumEntity entfernt, daher jetzt eine eigene Sensor-Entity.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: Robot360Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.sn}_battery"

    @property
    def device_info(self) -> dict:
        return self.coordinator.device_info

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data or {}
        for key in _BATTERY_KEYS:
            val = data.get(key)
            if val is None:
                continue
            try:
                return int(val)
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "Akkuwert %s=%r für %s nicht als Zahl lesbar",
                    key,
                    val,
                    self.coordinator.sn,
                )
        return None
