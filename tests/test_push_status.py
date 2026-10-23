import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from custom_components.vacuum_360.api import Api360
from custom_components.vacuum_360.sensor import Robot360BatterySensor


class _Response:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def json(self, **_kwargs):
        return {"errno": 0, "data": {}}


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


class _Push:
    def __init__(self, _sid, _pushkey, session):
        self.session = session
        self.reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def read_event(self):
        self.reads += 1
        task_id = self.session.calls[-1][1]["data"]["taskid"]
        return {
            "sn": "robot-1",
            "taskid": "unrelated" if self.reads == 1 else task_id,
            "data": json.dumps({
                "infoType": "20001",
                "data": {"elecReal": 81, "elec": 80, "mode": "fullcharge"},
            }),
        }


class PushStatusTest(unittest.TestCase):
    def test_status_from_matching_push_only(self):
        async def check():
            session = _Session()
            push = _Push("sid", "pushkey", session)
            api = Api360(session, "qid", "sid", "pushkey")
            with patch("custom_components.vacuum_360.api.PushClient", return_value=push):
                status = await api.get_status("robot-1")
            self.assertEqual(status["elecReal"], 81)
            self.assertEqual(push.reads, 2)
            self.assertEqual(len(session.calls), 1)
            payload = session.calls[0][1]["data"]
            self.assertEqual(payload["infoType"], "20001")
            self.assertEqual(payload["sn"], "robot-1")
            sensor = Robot360BatterySensor.__new__(Robot360BatterySensor)
            sensor.coordinator = type("Coordinator", (), {"data": status})()
            self.assertEqual(sensor.native_value, 81)

        asyncio.run(check())
