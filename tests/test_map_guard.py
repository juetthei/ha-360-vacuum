import asyncio
import unittest
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.vacuum_360.api import Api360Error
from custom_components.vacuum_360.map_guard import map_guard_state
from custom_components.vacuum_360.vacuum import Robot360Vacuum


EXPECTED = {
    "map_id": 1000000001,
    "vertices": [[3581, -3746], [991, -3746], [991, -2667], [3581, -2667]],
}


class MapGuardTest(unittest.TestCase):
    def test_only_the_known_zone_on_the_known_map_is_safe(self):
        zone = {"active": "forbid", "vertexs": list(reversed(EXPECTED["vertices"]))}
        current = {"mapId": EXPECTED["map_id"], "area": [zone]}
        self.assertEqual(map_guard_state(current, EXPECTED), "safe")
        self.assertEqual(map_guard_state({**current, "area": [{"active": "forbid", "vertexs": [
            [500, -4000], [4000, -4000], [4000, -2500], [500, -2500]
        ]}]}, EXPECTED), "safe")
        self.assertEqual(map_guard_state({**current, "area": []}, EXPECTED), "zone_missing")
        self.assertEqual(map_guard_state({**current, "mapId": 123}, EXPECTED), "wrong_map")
        self.assertEqual(map_guard_state({**current, "area": [
            {"active": "forbid", "vertexs": [[0, 0], [1, 0], [1, 1], [0, 1]]}
        ]}, EXPECTED), "zone_missing")
        self.assertEqual(map_guard_state({**current, "area": [
            {"active": "forbid", "vertexs": [[1000, -3746], [3581, -3746],
                                              [3581, -2667], [1000, -2667]]}
        ]}, EXPECTED), "zone_missing")
        self.assertEqual(map_guard_state({**current, "area": None}, EXPECTED), "check_failed")

    def test_missing_zone_blocks_ha_start(self):
        async def check():
            api = type("Api", (), {
                "get_current_map": AsyncMock(return_value={"mapId": EXPECTED["map_id"], "area": []}),
                "start": AsyncMock(),
            })()
            robot = Robot360Vacuum.__new__(Robot360Vacuum)
            robot.coordinator = type("Coordinator", (), {"sn": "upstairs", "api": api})()
            robot._start_blocked = False
            robot._map_guard = EXPECTED
            with self.assertRaises(HomeAssistantError):
                await robot.async_start()
            api.start.assert_not_awaited()

        asyncio.run(check())

    def test_known_zone_allows_mocked_ha_start(self):
        async def check():
            api = type("Api", (), {
                "get_current_map": AsyncMock(return_value={"mapId": EXPECTED["map_id"],
                    "area": [{"active": "forbid", "vertexs": EXPECTED["vertices"]}]}),
                "start": AsyncMock(),
            })()
            robot = Robot360Vacuum.__new__(Robot360Vacuum)
            robot.coordinator = type("Coordinator", (), {
                "sn": "upstairs", "api": api, "async_request_refresh": AsyncMock(),
            })()
            robot._start_blocked = False
            robot._map_guard = EXPECTED
            robot._set_optimistic = lambda _activity: None
            await robot.async_start()
            api.get_current_map.assert_awaited_once_with("upstairs")
            api.start.assert_awaited_once_with("upstairs")

        asyncio.run(check())

    def test_map_read_error_blocks_ha_start(self):
        async def check():
            api = type("Api", (), {
                "get_current_map": AsyncMock(side_effect=Api360Error("offline")),
                "start": AsyncMock(),
            })()
            robot = Robot360Vacuum.__new__(Robot360Vacuum)
            robot.coordinator = type("Coordinator", (), {"sn": "upstairs", "api": api})()
            robot._start_blocked = False
            robot._map_guard = EXPECTED
            with self.assertRaises(HomeAssistantError):
                await robot.async_start()
            api.start.assert_not_awaited()

        asyncio.run(check())
