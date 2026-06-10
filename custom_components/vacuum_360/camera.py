from __future__ import annotations

import io
import logging
from datetime import timedelta

from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import Robot360Coordinator

_LOGGER = logging.getLogger(__name__)

_CACHE_TTL = timedelta(minutes=5)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Robot360MapCamera(coord) for coord in coordinators.values()])


class Robot360MapCamera(Camera):
    """Camera entity rendering the latest known 360 cleaning path."""

    _attr_has_entity_name = True
    _attr_name = "Map"

    def __init__(self, coordinator: Robot360Coordinator) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.sn}_map"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.sn)},
            "name": coordinator.device_name,
            "manufacturer": "Qihoo 360",
            "model": "360 AI CleanRobot S6",
        }
        self._image: bytes | None = None
        self._last_update = None
        self._record: dict = {}

    @property
    def extra_state_attributes(self) -> dict:
        record = self._record or {}
        return {
            "clean_id": record.get("cleanId"),
            "clean_area": record.get("cleanArea") or record.get("sweep"),
            "clean_time": record.get("cleanTime"),
            "map_width": record.get("width"),
            "map_height": record.get("height"),
            "path_points": len(record.get("posArray") or []),
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        now = dt_util.utcnow()
        if self._image and self._last_update and now - self._last_update < _CACHE_TTL:
            return self._image

        try:
            record = await self.coordinator.api.get_latest_clean_record(self.coordinator.sn)
        except Exception as exc:
            _LOGGER.warning("Konnte 360-Karte nicht laden: %s", exc)
            return self._image

        if not record:
            return self._image

        self._record = record
        self._image = await self.hass.async_add_executor_job(_render_map, record)
        self._last_update = now
        self.async_write_ha_state()
        return self._image


def _render_map(record: dict) -> bytes:
    points = [
        (float(point[0]), float(point[1]))
        for point in record.get("posArray") or []
        if isinstance(point, list) and len(point) >= 2
    ]

    canvas_w = 900
    canvas_h = 700
    padding = 48
    image = Image.new("RGB", (canvas_w, canvas_h), "#f8faf7")
    draw = ImageDraw.Draw(image)

    if not points:
        draw.text((padding, padding), "Keine Kartendaten verfuegbar", fill="#334155")
        return _png_bytes(image)

    min_x = min(x for x, _ in points)
    max_x = max(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    span_x = max(max_x - min_x, 1)
    span_y = max(max_y - min_y, 1)
    scale = min((canvas_w - padding * 2) / span_x, (canvas_h - padding * 2) / span_y)

    def tx(point: tuple[float, float]) -> tuple[int, int]:
        x, y = point
        px = padding + (x - min_x) * scale
        py = canvas_h - padding - (y - min_y) * scale
        return int(px), int(py)

    mapped = [tx(point) for point in points]
    bounds = [tx((min_x, min_y)), tx((max_x, max_y))]
    draw.rectangle(
        [bounds[0][0], bounds[1][1], bounds[1][0], bounds[0][1]],
        outline="#cbd5c7",
        width=2,
    )

    if len(mapped) > 1:
        draw.line(mapped, fill="#0f766e", width=4, joint="curve")

    start = mapped[0]
    end = mapped[-1]
    draw.ellipse([start[0] - 7, start[1] - 7, start[0] + 7, start[1] + 7], fill="#22c55e")
    draw.ellipse([end[0] - 7, end[1] - 7, end[0] + 7, end[1] + 7], fill="#ef4444")

    title = "Cybersauger - letzte Reinigung"
    area = record.get("cleanArea") or record.get("sweep")
    duration = record.get("cleanTime")
    subtitle = f"Flaeche: {area or '?'} m2  Zeit: {duration or '?'} s  Punkte: {len(points)}"
    draw.text((padding, 18), title, fill="#0f172a")
    draw.text((padding, 36), subtitle, fill="#475569")

    return _png_bytes(image)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
