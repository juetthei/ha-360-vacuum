import asyncio
import unittest
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.vacuum_360.api import Api360
from custom_components.vacuum_360.vacuum import Robot360Vacuum


def _robot(data=None):
    api = type("Api", (), {"set_fan_speed": AsyncMock()})()
    robot = Robot360Vacuum.__new__(Robot360Vacuum)
    robot.coordinator = type("Coordinator", (), {
        "sn": "upstairs", "api": api, "data": data or {},
        "async_request_refresh": AsyncMock(),
    })()
    return robot, api


class FanSpeedTest(unittest.TestCase):
    def test_reports_fan_speed_from_status(self):
        self.assertEqual(_robot({"workNoisy": "strong"})[0].fan_speed, "Power")
        self.assertEqual(_robot({"workNoisy": "quiet"})[0].fan_speed, "Leise")
        self.assertIsNone(_robot({"workNoisy": "max"})[0].fan_speed)

    def test_sets_fan_speed_with_app_command(self):
        async def check():
            api = Api360(None, "qid", "sid")
            api.send_cmd = AsyncMock()
            await api.set_fan_speed("upstairs", "auto")
            api.send_cmd.assert_awaited_once_with("upstairs", "21022", {"cmd": "auto"})

        asyncio.run(check())

    def test_unknown_fan_speed_sends_nothing(self):
        async def check():
            robot, api = _robot()
            with self.assertRaises(HomeAssistantError):
                await robot.async_set_fan_speed("Turbo")
            api.set_fan_speed.assert_not_awaited()
            await robot.async_set_fan_speed("Leise")
            api.set_fan_speed.assert_awaited_once_with("upstairs", "quiet")

        asyncio.run(check())


class LocateTest(unittest.TestCase):
    def test_locate_uses_library_command(self):
        async def check():
            api = Api360(None, "qid", "sid")
            api.send_cmd = AsyncMock()
            await api.locate("upstairs")
            api.send_cmd.assert_awaited_once_with("upstairs", "21020", {"ctrlCode": 3010})

        asyncio.run(check())
