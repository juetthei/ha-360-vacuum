import unittest

from custom_components.vacuum_360.camera import _decompress_map


class MapDecodeTest(unittest.TestCase):
    def test_lz4_literals_and_back_reference(self):
        self.assertEqual(_decompress_map(b"\x40ABCD\x04\x00", 8), b"ABCDABCD")

    def test_rejects_invalid_offset(self):
        with self.assertRaises(ValueError):
            _decompress_map(b"\x00\x01\x00", 4)
