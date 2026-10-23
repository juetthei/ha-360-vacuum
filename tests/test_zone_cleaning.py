import asyncio
import unittest
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.vacuum_360.api import Api360
from custom_components.vacuum_360.zones import async_start_saved_zone


GUARD = {
    "map_id": 1000000001,
    "vertices": [[3581, -3746], [991, -3746], [991, -2667], [3581, -2667]],
}
ZONE = {
    "id": "schlafzimmer_oben",
    "map_id": 1000000001,
    "vertices": [[-176, -3270], [-3455, -3270], [-3455, 1], [-176, 1]],
    "source_area_id": 2,
    "source_area_name": "rect2",
    "confirmed_by_user": True,
}
CURRENT = {
    "mapId": 1000000001,
    "area": [{"active": "forbid", "vertexs": GUARD["vertices"]}],
}


class ZoneCleaningTest(unittest.TestCase):
    def test_uses_app_rectangle_command(self):
        async def check():
            api = Api360(None, "qid", "sid")
            api.send_cmd = AsyncMock(return_value={})
            await api.clean_zone("robot-1", ZONE["map_id"], ZONE)
            api.send_cmd.assert_awaited_once_with("robot-1", "30000", {
                "cmds": [
                    {"infoType": "21023", "data": {
                        "mapId": ZONE["map_id"], "cleanId": [-2], "extraAreas": [{
                            "vertexs": ZONE["vertices"], "active": "normal",
                            "name": "rect2", "tag": "", "id": 2, "mode": "default",
                        }],
                    }},
                    {"infoType": "21005", "data": {"mode": "reAppointClean"}},
                ],
                "mainCmds": ["21005"],
            })

        asyncio.run(check())

    def test_stale_or_unprotected_map_never_starts_zone(self):
        async def check():
            api = type("Api", (), {
                "get_current_map": AsyncMock(return_value={**CURRENT, "area": []}),
                "get_status": AsyncMock(return_value={"mode": "charge"}),
                "clean_zone": AsyncMock(),
            })()
            with self.assertRaises(HomeAssistantError):
                await async_start_saved_zone(api, "robot-1", ZONE, GUARD)
            api.get_status.assert_not_awaited()
            api.clean_zone.assert_not_awaited()
            api.get_current_map.return_value = {**CURRENT, "mapId": 999}
            with self.assertRaises(HomeAssistantError):
                await async_start_saved_zone(api, "robot-1", ZONE, GUARD)
            api.clean_zone.assert_not_awaited()

        asyncio.run(check())

    def test_confirmed_zone_starts_only_when_docked(self):
        async def check():
            api = type("Api", (), {
                "get_current_map": AsyncMock(return_value=CURRENT),
                "get_status": AsyncMock(return_value={"mode": "sweep"}),
                "clean_zone": AsyncMock(),
            })()
            with self.assertRaises(HomeAssistantError):
                await async_start_saved_zone(api, "robot-1", ZONE, GUARD)
            api.clean_zone.assert_not_awaited()
            api.get_status.return_value = {"mode": "charge"}
            await async_start_saved_zone(api, "robot-1", ZONE, GUARD)
            api.clean_zone.assert_awaited_once_with("robot-1", ZONE["map_id"], ZONE)

        asyncio.run(check())
