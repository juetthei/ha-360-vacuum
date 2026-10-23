"""Map of the last completed cleaning, rendered from the 360 cloud record."""

import base64
import logging
from datetime import timedelta

from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import Api360Error
from .const import DOMAIN
from .coordinator import Robot360Coordinator

_LOGGER = logging.getLogger(__name__)
_CACHE_AGE = timedelta(minutes=5)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Robot360Map(coord) for coord in coordinators.values()])


class Robot360Map(Camera):
    _attr_has_entity_name = True
    _attr_name = "Karte"

    def __init__(self, coordinator: Robot360Coordinator) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.sn}_map"
        self._image: bytes | None = None
        self._updated = None

    @property
    def device_info(self) -> dict:
        return self.coordinator.device_info

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        now = dt_util.utcnow()
        if self._image and self._updated and now - self._updated < _CACHE_AGE:
            return self._image
        try:
            record = await self.coordinator.api.get_latest_clean_record(self.coordinator.sn)
            if record:
                self._image = await self.hass.async_add_executor_job(_render_map, record)
                self._updated = now
        except (Api360Error, ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            _LOGGER.warning("Karte konnte nicht gezeichnet werden: %s", exc)
        return self._image


def _decompress_map(data: bytes, size: int) -> bytes:
    """Decode the LZ4 block stored in a 360 cleaning record."""
    out = bytearray()
    i = 0
    while i < len(data):
        token = data[i]
        i += 1
        literal_size = token >> 4
        if literal_size == 15:
            while True:
                extra = data[i]
                i += 1
                literal_size += extra
                if extra != 255:
                    break
        if i + literal_size > len(data) or len(out) + literal_size > size:
            raise ValueError("Invalid map literal length")
        out.extend(data[i : i + literal_size])
        i += literal_size
        if i == len(data):
            break
        if i + 2 > len(data):
            raise ValueError("Truncated map offset")
        offset = int.from_bytes(data[i : i + 2], "little")
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError("Invalid map offset")
        match_size = (token & 15) + 4
        if token & 15 == 15:
            while True:
                extra = data[i]
                i += 1
                match_size += extra
                if extra != 255:
                    break
        if len(out) + match_size > size:
            raise ValueError("Invalid map match length")
        for _ in range(match_size):
            out.append(out[-offset])
    if len(out) != size:
        raise ValueError("Unexpected map size")
    return bytes(out)


def _render_map(record: dict) -> bytes:
    width, height = int(record["width"]), int(record["height"])
    if not 0 < width <= 2048 or not 0 < height <= 2048:
        raise ValueError("Invalid map dimensions")
    pixels = _decompress_map(base64.b64decode(record["map"]), width * height)
    palette = {127: (32, 44, 57), 255: (219, 235, 220), 0: (82, 103, 116)}
    image = Image.new("RGB", (width, height))
    image.putdata([palette.get(pixel, (150, 160, 165)) for pixel in pixels])
    draw = ImageDraw.Draw(image)
    resolution = float(record["resolution"])
    if resolution <= 0:
        raise ValueError("Invalid map resolution")
    x_min, y_min = float(record["x_min"]), float(record["y_min"])
    points = [
        (
            round((point[0] / 1000 - x_min) / resolution),
            round((point[1] / 1000 - y_min) / resolution),
        )
        for point in record.get("posArray") or []
        if isinstance(point, list) and len(point) >= 2
    ]
    if len(points) > 1:
        draw.line(points, fill=(242, 137, 68), width=1)
    image = image.resize((width * 4, height * 4), Image.Resampling.NEAREST)
    from io import BytesIO

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
