import asyncio
import unittest
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.vacuum_360.vacuum import Robot360Vacuum


class StartBlockTest(unittest.TestCase):
    def test_blocked_robot_never_receives_start_command(self):
        async def check():
            api = type("Api", (), {"start": AsyncMock()})()
            robot = Robot360Vacuum.__new__(Robot360Vacuum)
            robot.coordinator = type("Coordinator", (), {"sn": "upstairs", "api": api})()
            robot._start_blocked = True
            with self.assertRaises(HomeAssistantError):
                await robot.async_start()
            api.start.assert_not_awaited()

        asyncio.run(check())
