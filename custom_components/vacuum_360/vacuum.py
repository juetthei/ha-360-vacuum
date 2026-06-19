import logging

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_MAP
from .coordinator import Robot360Coordinator

_LOGGER = logging.getLogger(__name__)

_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STATE
)

_ACTIVITY_MAP: dict[str, VacuumActivity] = {
    "cleaning":  VacuumActivity.CLEANING,
    "docked":    VacuumActivity.DOCKED,
    "paused":    VacuumActivity.PAUSED,
    "idle":      VacuumActivity.IDLE,
    "returning": VacuumActivity.RETURNING,
    "error":     VacuumActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Robot360Vacuum(coord) for coord in coordinators.values()])


class Robot360Vacuum(CoordinatorEntity[Robot360Coordinator], StateVacuumEntity):
    _attr_supported_features = _FEATURES
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: Robot360Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.sn
        self._optimistic_activity: VacuumActivity | None = None

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator.sn)},
            "name": self.coordinator.device_name,
            "manufacturer": "Qihoo 360",
            "model": "360 AI CleanRobot S6",
        }

    @property
    def activity(self) -> VacuumActivity | None:
        if self._optimistic_activity is not None:
            return self._optimistic_activity

        data = self.coordinator.data or {}
        mode = (
            data.get("mode")
            or data.get("workMode")
            or data.get("runStatus")
            or data.get("cleanMode")
        )
        if not mode:
            if data.get("online") in (1, "1", True):
                return VacuumActivity.IDLE
            return None

        ha_state = MODE_MAP.get(str(mode), "idle")
        return _ACTIVITY_MAP.get(ha_state, VacuumActivity.IDLE)

    def _handle_coordinator_update(self) -> None:
        self._optimistic_activity = None
        super()._handle_coordinator_update()

    async def async_start(self) -> None:
        self._optimistic_activity = VacuumActivity.CLEANING
        self.async_write_ha_state()
        await self.coordinator.api.start(self.coordinator.sn)
        await self.coordinator.async_request_refresh()

    async def async_stop(self, **kwargs) -> None:
        await self.async_return_to_base()

    async def async_return_to_base(self, **kwargs) -> None:
        self._optimistic_activity = VacuumActivity.RETURNING
        self.async_write_ha_state()
        await self.coordinator.api.return_to_base(self.coordinator.sn)
        await self.coordinator.async_request_refresh()

    async def async_pause(self) -> None:
        self._optimistic_activity = VacuumActivity.PAUSED
        self.async_write_ha_state()
        await self.coordinator.api.pause(self.coordinator.sn)
        await self.coordinator.async_request_refresh()
