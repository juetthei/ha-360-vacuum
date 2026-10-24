"""Check that known forbidden areas are still on the active map."""

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import Api360Error
from .coordinator import Robot360Coordinator

_LOGGER = logging.getLogger(__name__)


def map_guard_state(current: dict, expected: dict) -> str:
    """Return a state that never treats an unknown map as safe."""
    if str(current.get("mapId")) != str(expected["map_id"]):
        return "wrong_map"

    areas = current.get("area")
    if not isinstance(areas, list):
        return "check_failed"
    for wanted in expected.get("areas") or [expected["vertices"]]:
        if not _forbid_area_covers(areas, wanted):
            return "zone_missing"
    return "safe"


def _forbid_area_covers(areas: list, wanted: list) -> bool:
    wanted_x = [point[0] for point in wanted]
    wanted_y = [point[1] for point in wanted]
    for area in areas:
        if not isinstance(area, dict) or area.get("active") != "forbid":
            continue
        vertices = area.get("vertexs")
        if not isinstance(vertices, list) or len(vertices) != 4:
            continue
        points = {tuple(point) for point in vertices}
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        if points != {
            (min(x_values), min(y_values)),
            (min(x_values), max(y_values)),
            (max(x_values), min(y_values)),
            (max(x_values), max(y_values)),
        }:
            continue
        if (min(x_values) <= min(wanted_x) and max(x_values) >= max(wanted_x)
                and min(y_values) <= min(wanted_y) and max(y_values) >= max(wanted_y)):
            return True
    return False


class Robot360MapGuardCoordinator(DataUpdateCoordinator[str]):
    def __init__(self, coordinator: Robot360Coordinator, expected: dict) -> None:
        super().__init__(
            coordinator.hass,
            _LOGGER,
            name=f"vacuum_360_map_guard_{coordinator.sn}",
            update_interval=timedelta(minutes=5),
        )
        self.robot = coordinator
        self.expected = expected

    async def _async_update_data(self) -> str:
        try:
            current = await self.robot.api.get_current_map(self.robot.sn)
            return map_guard_state(current, self.expected)
        except (Api360Error, KeyError, TypeError, ValueError):
            return "check_failed"
