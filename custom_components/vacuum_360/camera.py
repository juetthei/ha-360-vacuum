from __future__ import annotations

import io
import logging
import math
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

_LIVE_CACHE_TTL = timedelta(seconds=5)
_RECORD_CACHE_TTL = timedelta(minutes=5)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, Robot360Coordinator] = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for coord in coordinators.values():
        entities.append(Robot360MapCamera(coord, "2d"))
        entities.append(Robot360MapCamera(coord, "3d"))
    async_add_entities(entities)


class Robot360MapCamera(Camera):
    """Camera entity rendering live or latest known 360 cleaning map data."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Robot360Coordinator, mode: str) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.mode = mode
        self._attr_name = "3D Map" if mode == "3d" else "Map"
        self._attr_unique_id = (
            f"{coordinator.sn}_map_3d" if mode == "3d" else f"{coordinator.sn}_map"
        )
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
            "source": record.get("source", "record"),
            "clean_id": record.get("cleanId"),
            "clean_area": record.get("cleanArea") or record.get("sweep"),
            "clean_time": record.get("cleanTime"),
            "map_width": record.get("width"),
            "map_height": record.get("height"),
            "path_points": len(_points_from_record(record)),
            "rooms": len(_areas_from_record(record)),
            "render_mode": self.mode,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        now = dt_util.utcnow()
        ttl = _LIVE_CACHE_TTL if self._record.get("source") == "live" else _RECORD_CACHE_TTL
        if self._image and self._last_update and now - self._last_update < ttl:
            return self._image

        try:
            record = await self.coordinator.api.get_live_clean_snapshot(self.coordinator.sn)
            if not record:
                record = await self.coordinator.api.get_latest_clean_record(self.coordinator.sn)
        except Exception as exc:
            _LOGGER.warning("Konnte 360-Karte nicht laden: %s", exc)
            return self._image

        if not record:
            return self._image

        self._record = record
        self._image = await self.hass.async_add_executor_job(_render_map, record, self.mode)
        self._last_update = now
        self.async_write_ha_state()
        return self._image


def _render_map(record: dict, mode: str) -> bytes:
    points = _points_from_record(record)
    areas = _areas_from_record(record)
    robot_pos = _robot_pos(record, points)

    if mode == "3d":
        return _png_bytes(_render_isometric(record, points, areas, robot_pos))
    return _png_bytes(_render_topdown(record, points, areas, robot_pos))


def _points_from_record(record: dict) -> list[tuple[float, float]]:
    return [
        (float(point[0]), float(point[1]))
        for point in record.get("posArray") or []
        if isinstance(point, list) and len(point) >= 2
    ]


def _areas_from_record(record: dict) -> list[dict]:
    raw_areas = []
    for key in ("area", "cliparea"):
        raw_areas.extend(record.get(key) or [])
    smart_area = record.get("smartArea") or {}
    raw_areas.extend(smart_area.get("value") or [])

    areas = []
    for area in raw_areas:
        vertexes = area.get("vertexs") or area.get("vertices") or []
        points = [
            (float(vertex[0]), float(vertex[1]))
            for vertex in vertexes
            if isinstance(vertex, list) and len(vertex) >= 2
        ]
        if len(points) >= 2:
            areas.append(
                {
                    "points": points,
                    "name": area.get("name") or area.get("roomType") or "",
                    "active": area.get("active") or "",
                }
            )
    return areas


def _robot_pos(record: dict, points: list[tuple[float, float]]) -> tuple[float, float] | None:
    pos = record.get("pos")
    if isinstance(pos, list) and len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    return points[-1] if points else None


def _bounds(
    points: list[tuple[float, float]], areas: list[dict], robot_pos: tuple[float, float] | None
) -> tuple[float, float, float, float]:
    all_points = list(points)
    for area in areas:
        all_points.extend(area["points"])
    if robot_pos:
        all_points.append(robot_pos)
    if not all_points:
        return 0, 1, 0, 1
    min_x = min(x for x, _ in all_points)
    max_x = max(x for x, _ in all_points)
    min_y = min(y for _, y in all_points)
    max_y = max(y for _, y in all_points)
    return min_x, max_x, min_y, max_y


def _render_topdown(
    record: dict,
    points: list[tuple[float, float]],
    areas: list[dict],
    robot_pos: tuple[float, float] | None,
) -> Image.Image:
    canvas_w = 1100
    canvas_h = 820
    padding = 70
    image = Image.new("RGB", (canvas_w, canvas_h), "#f5f7f1")
    draw = ImageDraw.Draw(image)

    if not points and not areas:
        draw.text((padding, padding), "Keine Kartendaten verfuegbar", fill="#334155")
        return image

    min_x, max_x, min_y, max_y = _bounds(points, areas, robot_pos)
    span_x = max(max_x - min_x, 1)
    span_y = max(max_y - min_y, 1)
    scale = min((canvas_w - padding * 2) / span_x, (canvas_h - padding * 2) / span_y)

    def tx(point: tuple[float, float]) -> tuple[int, int]:
        x, y = point
        px = padding + (x - min_x) * scale
        py = canvas_h - padding - (y - min_y) * scale
        return int(px), int(py)

    _draw_header(draw, record, points, "Live Map" if record.get("source") == "live" else "Letzte Reinigung")
    _draw_grid(draw, canvas_w, canvas_h, padding)

    for idx, area in enumerate(areas):
        mapped_area = [tx(point) for point in area["points"]]
        color = "#d7ebe3" if idx % 2 == 0 else "#e4edd6"
        if len(mapped_area) >= 3:
            draw.polygon(mapped_area, fill=color, outline="#8aa99a")
        else:
            draw.line(mapped_area, fill="#8aa99a", width=4)

    if len(points) > 1:
        mapped = [tx(point) for point in points]
        draw.line(mapped, fill="#b8ddd3", width=10, joint="curve")
        draw.line(mapped, fill="#0f766e", width=4, joint="curve")
        _draw_marker(draw, mapped[0], "#22c55e")
        _draw_marker(draw, mapped[-1], "#ef4444")

    if robot_pos:
        _draw_robot(draw, tx(robot_pos), record.get("phi"))

    return image


def _render_isometric(
    record: dict,
    points: list[tuple[float, float]],
    areas: list[dict],
    robot_pos: tuple[float, float] | None,
) -> Image.Image:
    canvas_w = 1100
    canvas_h = 820
    padding = 80
    image = Image.new("RGB", (canvas_w, canvas_h), "#eef4ef")
    draw = ImageDraw.Draw(image)

    if not points and not areas:
        draw.text((padding, padding), "Keine Kartendaten verfuegbar", fill="#334155")
        return image

    min_x, max_x, min_y, max_y = _bounds(points, areas, robot_pos)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    projected = [_iso(point, cx, cy) for point in points]
    for area in areas:
        projected.extend(_iso(point, cx, cy) for point in area["points"])
    if robot_pos:
        projected.append(_iso(robot_pos, cx, cy))

    min_ix = min(x for x, _ in projected)
    max_ix = max(x for x, _ in projected)
    min_iy = min(y for _, y in projected)
    max_iy = max(y for _, y in projected)
    scale = min(
        (canvas_w - padding * 2) / max(max_ix - min_ix, 1),
        (canvas_h - padding * 2) / max(max_iy - min_iy, 1),
    )

    def tx(point: tuple[float, float]) -> tuple[int, int]:
        ix, iy = _iso(point, cx, cy)
        return (
            int(padding + (ix - min_ix) * scale),
            int(padding + (iy - min_iy) * scale),
        )

    _draw_header(draw, record, points, "3D Live Map" if record.get("source") == "live" else "3D letzte Reinigung")

    for idx, area in enumerate(areas):
        mapped_area = [tx(point) for point in area["points"]]
        if len(mapped_area) >= 3:
            base = [(x, y + 16) for x, y in mapped_area]
            draw.polygon(base, fill="#a6b7a8")
            draw.polygon(mapped_area, fill="#d8eadf" if idx % 2 == 0 else "#e8efd9", outline="#7f9a86")

    if len(points) > 1:
        mapped = [tx(point) for point in points]
        for offset, color, width in ((18, "#8ca698", 9), (8, "#9ec7b9", 7), (0, "#0f766e", 4)):
            draw.line([(x, y + offset) for x, y in mapped], fill=color, width=width, joint="curve")
        _draw_marker(draw, mapped[0], "#22c55e")
        _draw_marker(draw, mapped[-1], "#ef4444")

    if robot_pos:
        _draw_robot(draw, tx(robot_pos), record.get("phi"), radius=14)

    return image


def _iso(point: tuple[float, float], cx: float, cy: float) -> tuple[float, float]:
    x, y = point
    x -= cx
    y -= cy
    return (x - y) * 0.72, (x + y) * 0.36


def _draw_header(draw: ImageDraw.ImageDraw, record: dict, points: list[tuple[float, float]], title: str) -> None:
    area = record.get("cleanArea") or record.get("sweep")
    duration = record.get("cleanTime")
    source = record.get("source", "record")
    subtitle = f"Quelle: {source}  Flaeche: {area or '?'} m2  Zeit: {duration or '?'} s  Punkte: {len(points)}"
    draw.text((48, 22), f"Cybersauger - {title}", fill="#0f172a")
    draw.text((48, 44), subtitle, fill="#475569")


def _draw_grid(draw: ImageDraw.ImageDraw, width: int, height: int, padding: int) -> None:
    for x in range(padding, width - padding + 1, 80):
        draw.line([(x, padding), (x, height - padding)], fill="#e3eadf", width=1)
    for y in range(padding, height - padding + 1, 80):
        draw.line([(padding, y), (width - padding, y)], fill="#e3eadf", width=1)


def _draw_marker(draw: ImageDraw.ImageDraw, point: tuple[int, int], color: str) -> None:
    x, y = point
    draw.ellipse([x - 8, y - 8, x + 8, y + 8], fill=color, outline="#ffffff", width=2)


def _draw_robot(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    phi: int | float | None,
    radius: int = 12,
) -> None:
    x, y = point
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill="#111827", outline="#ffffff", width=3)
    if phi is None:
        return
    angle = math.radians(float(phi) - 90)
    tip = (x + int(math.cos(angle) * radius * 1.6), y + int(math.sin(angle) * radius * 1.6))
    left = (x + int(math.cos(angle + 2.4) * radius), y + int(math.sin(angle + 2.4) * radius))
    right = (x + int(math.cos(angle - 2.4) * radius), y + int(math.sin(angle - 2.4) * radius))
    draw.polygon([tip, left, right], fill="#111827")


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
