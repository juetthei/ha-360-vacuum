import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.vacuum_360.api import Api360
from custom_components.vacuum_360.const import CONF_BLOCKED_START_SNS, CONF_MAP_GUARDS, DOMAIN
from custom_components.vacuum_360.zones import async_clean_zone, async_start_saved_zone


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
MULTI_ZONE = {
    "id": "flur_oben",
    "map_id": ZONE["map_id"],
    "confirmed_by_user": True,
    "areas": [
        {"vertices": [[100, 0], [0, 0], [0, 100], [100, 100]],
         "source_area_id": 2, "source_area_name": "rect2"},
        {"vertices": [[200, 0], [100, 0], [100, 100], [200, 100]],
         "source_area_id": 3, "source_area_name": "rect3"},
    ],
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

    def test_two_rectangles_use_one_command(self):
        async def check():
            api = Api360(None, "qid", "sid")
            api.send_cmd = AsyncMock(return_value={})
            await api.clean_zone("robot-1", MULTI_ZONE["map_id"], MULTI_ZONE)
            api.send_cmd.assert_awaited_once()
            sn, command, payload = api.send_cmd.await_args.args
            self.assertEqual((sn, command), ("robot-1", "30000"))
            self.assertEqual(payload["mainCmds"], ["21005"])
            self.assertEqual(payload["cmds"][0]["data"]["extraAreas"], [
                {"vertexs": item["vertices"], "active": "normal",
                 "name": item["source_area_name"], "tag": "",
                 "id": item["source_area_id"], "mode": "default"}
                for item in MULTI_ZONE["areas"]
            ])

        asyncio.run(check())

    def test_two_rectangles_validate_before_start(self):
        async def check():
            api = type("Api", (), {
                "get_current_map": AsyncMock(return_value=CURRENT),
                "get_status": AsyncMock(return_value={"mode": "charge"}),
                "clean_zone": AsyncMock(),
            })()
            invalid = {**MULTI_ZONE, "areas": [
                MULTI_ZONE["areas"][0],
                {**MULTI_ZONE["areas"][1], "vertices": [[0, 0]]},
            ]}
            with self.assertRaises(ServiceValidationError):
                await async_start_saved_zone(api, "robot-1", invalid, GUARD)
            api.get_status.assert_not_awaited()
            api.clean_zone.assert_not_awaited()
            invalid["areas"][1]["vertices"] = [[0, 0], [0, 0], [100, 100], [100, 100]]
            with self.assertRaises(ServiceValidationError):
                await async_start_saved_zone(api, "robot-1", invalid, GUARD)
            api.clean_zone.assert_not_awaited()
            await async_start_saved_zone(api, "robot-1", MULTI_ZONE, GUARD)
            api.clean_zone.assert_awaited_once_with(
                "robot-1", MULTI_ZONE["map_id"], MULTI_ZONE
            )

        asyncio.run(check())

    def test_static_start_block_also_blocks_saved_zone(self):
        async def check():
            api = SimpleNamespace(get_current_map=AsyncMock(), clean_zone=AsyncMock())
            robot = SimpleNamespace(api=api, async_request_refresh=AsyncMock())
            entry = SimpleNamespace(entry_id="entry", options={
                CONF_MAP_GUARDS: {"robot-1": GUARD},
                CONF_BLOCKED_START_SNS: ["robot-1"],
            })
            hass = SimpleNamespace(
                config_entries=SimpleNamespace(async_entries=Mock(return_value=[entry])),
                data={DOMAIN: {"entry": {"robot-1": robot}}},
            )
            with patch("custom_components.vacuum_360.zones.Store") as store:
                store.return_value.async_load = AsyncMock(
                    return_value={"zones": [{**ZONE, "sn": "robot-1"}]}
                )
                with self.assertRaises(HomeAssistantError):
                    await async_clean_zone(
                        hass, SimpleNamespace(data={"zone_id": ZONE["id"]})
                    )
            api.get_current_map.assert_not_awaited()
            api.clean_zone.assert_not_awaited()

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
