import asyncio
import base64
import json
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from PIL import Image

from custom_components.vacuum_360.api import Api360, _MAP_LOAD_DATA
from custom_components.vacuum_360.camera import _decompress_map, _render_map


class MapDecodeTest(unittest.TestCase):
    def test_lz4_literals_and_back_reference(self):
        self.assertEqual(_decompress_map(b"\x40ABCD\x04\x00", 8), b"ABCDABCD")

    def test_rejects_invalid_offset(self):
        with self.assertRaises(ValueError):
            _decompress_map(b"\x00\x01\x00", 4)

    def test_forbidden_polygon_is_drawn_on_map(self):
        record = {
            "width": 4, "height": 4, "resolution": 1, "x_min": 0, "y_min": 0,
            "map": base64.b64encode(b"\xf0\x01" + b"\xff" * 16).decode(),
            "area": [{"active": "forbid", "vertexs": [
                [1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000],
            ]}],
        }
        image = Image.open(BytesIO(_render_map(record)))
        self.assertLess(image.getpixel((0, 0))[0], image.getpixel((0, 0))[1])
        self.assertGreater(image.getpixel((8, 8))[0], image.getpixel((8, 8))[1])

    def test_current_map_uses_read_only_request(self):
        class Push:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            async def read_event(self):
                return {"sn": "robot-1", "data": json.dumps({
                    "infoType": "20002", "data": {"map": "encoded", "area": [
                        {"active": "forbid", "vertexs": [[1, 2], [3, 4], [5, 6]]}
                    ]},
                })}

        async def check():
            api = Api360(None, "qid", "sid", "pushkey")
            api.send_cmd = AsyncMock(return_value={})
            with patch("custom_components.vacuum_360.api.PushClient", return_value=Push()):
                current = await api.get_current_map("robot-1")
            api.send_cmd.assert_awaited_once_with("robot-1", "30000", _MAP_LOAD_DATA)
            self.assertEqual(current["area"][0]["active"], "forbid")

        asyncio.run(check())
