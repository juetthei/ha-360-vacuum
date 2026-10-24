import logging

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Api360Error
from .const import CONF_BLOCKED_START_SNS, CONF_MAP_GUARDS, DOMAIN, FAN_SPEEDS, MODE_MAP
from .coordinator import Robot360Coordinator
from .map_guard import map_guard_state

_LOGGER = logging.getLogger(__name__)

_FEATURES = (
    VacuumEntityFeature.START
    | VacuumEntityFeature.STOP
    | VacuumEntityFeature.RETURN_HOME
    | VacuumEntityFeature.PAUSE
    | VacuumEntityFeature.STATE
    | VacuumEntityFeature.FAN_SPEED
)

_ACTIVITY_MAP: dict[str, VacuumActivity] = {
    "cleaning":  VacuumActivity.CLEANING,
    "docked":    VacuumActivity.DOCKED,
    "paused":    VacuumActivity.PAUSED,
    "idle":      VacuumActivity.IDLE,
    "returning": VacuumActivity.RETURNING,
    "error":     VacuumActivity.ERROR,
}

# Wie viele Coordinator-Updates der optimistische Status gehalten wird
_OPTIMISTIC_HOLD_CYCLES = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    blocked = set(entry.options.get(CONF_BLOCKED_START_SNS, []))
    guards = entry.options.get(CONF_MAP_GUARDS, {})
    async_add_entities([Robot360Vacuum(coord, coord.sn in blocked, guards.get(coord.sn))
                        for coord in coordinators.values()])


class Robot360Vacuum(CoordinatorEntity[Robot360Coordinator], StateVacuumEntity):
    _attr_supported_features = _FEATURES
    _attr_has_entity_name = True
    _attr_name = None
    _attr_fan_speed_list = list(FAN_SPEEDS)

    def __init__(self, coordinator: Robot360Coordinator, start_blocked: bool = False,
                 map_guard: dict | None = None) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.sn
        self._start_blocked = start_blocked
        self._map_guard = map_guard
        if start_blocked:
            self._attr_supported_features = _FEATURES & ~VacuumEntityFeature.START
        self._optimistic_activity: VacuumActivity | None = None
        self._optimistic_cycles_left: int = 0

    @property
    def device_info(self) -> dict:
        return self.coordinator.device_info

    @property
    def activity(self) -> VacuumActivity | None:
        # Optimistischer Status solange Zyklen übrig
        if self._optimistic_activity is not None and self._optimistic_cycles_left > 0:
            return self._optimistic_activity

        data = self.coordinator.data or {}

        # Echten Modus aus API-Daten lesen (falls verfügbar)
        mode = (
            data.get("mode")
            or data.get("workMode")
            or data.get("runStatus")
            or data.get("cleanMode")
        )
        if mode:
            ha_state = MODE_MAP.get(str(mode), "idle")
            return _ACTIVITY_MAP.get(ha_state, VacuumActivity.IDLE)

        # Fallback: wenn online → idle statt unknown
        if data.get("online") == 1:
            return VacuumActivity.IDLE

        return None

    @property
    def fan_speed(self) -> str | None:
        mode = (self.coordinator.data or {}).get("workNoisy")
        return next((name for name, value in FAN_SPEEDS.items() if value == mode), None)

    def _handle_coordinator_update(self) -> None:
        if self._optimistic_cycles_left > 0:
            self._optimistic_cycles_left -= 1
            if self._optimistic_cycles_left == 0:
                self._optimistic_activity = None
        super()._handle_coordinator_update()

    def _set_optimistic(self, activity: VacuumActivity) -> None:
        self._optimistic_activity = activity
        self._optimistic_cycles_left = _OPTIMISTIC_HOLD_CYCLES
        self.async_write_ha_state()

    async def async_start(self) -> None:
        if self._start_blocked:
            raise HomeAssistantError("Start für diesen Roboter in Home Assistant gesperrt")
        if self._map_guard:
            try:
                current = await self.coordinator.api.get_current_map(self.coordinator.sn)
                state = map_guard_state(current, self._map_guard)
            except (Api360Error, KeyError, TypeError, ValueError) as exc:
                raise HomeAssistantError("Treppensperre konnte nicht geprüft werden") from exc
            if state != "safe":
                raise HomeAssistantError(f"Start verweigert: Treppensperre {state}")
        self._set_optimistic(VacuumActivity.CLEANING)
        await self.coordinator.api.start(self.coordinator.sn)
        await self.coordinator.async_request_refresh()

    async def async_stop(self, **kwargs) -> None:
        await self.async_return_to_base()

    async def async_return_to_base(self, **kwargs) -> None:
        self._set_optimistic(VacuumActivity.RETURNING)
        await self.coordinator.api.return_to_base(self.coordinator.sn)
        await self.coordinator.async_request_refresh()

    async def async_pause(self) -> None:
        self._set_optimistic(VacuumActivity.PAUSED)
        await self.coordinator.api.pause(self.coordinator.sn)
        await self.coordinator.async_request_refresh()

    async def async_set_fan_speed(self, fan_speed: str, **kwargs) -> None:
        if fan_speed not in FAN_SPEEDS:
            raise HomeAssistantError(f"Unbekannte Saugstärke: {fan_speed}")
        await self.coordinator.api.set_fan_speed(self.coordinator.sn, FAN_SPEEDS[fan_speed])
        await self.coordinator.async_request_refresh()
