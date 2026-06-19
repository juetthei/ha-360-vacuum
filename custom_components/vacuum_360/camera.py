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
    async_add_entities([Robot360MapCamera(coord) for coord in coordinators.values()])


class Robot360MapCamera(Camera):
    """Camera entity rendering live or latest known 360 cleaning map data."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Robot360Coordinator) -> None:
        super().__init__()
        self.coordinator = coordinator
        self._attr_name = "Map"
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
        transform = _map_transform(record)
        return {
            "source": record.get("source", "record"),
            "clean_id": record.get("cleanId"),
            "clean_area": record.get("cleanArea") or record.get("sweep"),
            "approx_map_area_m2": _estimated_area(record),
            "approx_cleaned_area_m2": _cleaned_area(record),
            "coverage_percent": _coverage_percent(record),
            "clean_time": record.get("cleanTime"),
            "map_width": record.get("width"),
            "map_height": record.get("height"),
            "path_points": len(_points_from_record(record)),
            "rooms": len(_areas_from_record(record)),
            "objects": len(_objects_from_record(record)),
            "obstacles": record.get("obstaclesTimes", 0),
            "render_mode": "2d",
            "map_transform": transform,
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
        self._image = await self.hass.async_add_executor_job(_render_map, record)
        self._last_update = now
        self.async_write_ha_state()
        return self._image


def _render_map(record: dict) -> bytes:
    points = _points_from_record(record)
    areas = _areas_from_record(record)
    objects = _objects_from_record(record)
    robot_pos = _robot_pos(record, points)

    return _png_bytes(_render_topdown(record, points, areas, objects, robot_pos))


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


def _objects_from_record(record: dict) -> list[dict]:
    objects = []
    for key in (
        "furniture",
        "furnitureInfo",
        "furnitures",
        "objects",
        "objectList",
        "obstacles",
        "obstacleList",
        "aiObstacles",
        "avoidObjects",
    ):
        for item in record.get(key) or []:
            pos = (
                item.get("pos")
                or item.get("position")
                or item.get("point")
                or item.get("center")
                or item.get("coordinate")
            )
            if not isinstance(pos, list) or len(pos) < 2:
                x = item.get("x") or item.get("pointX") or item.get("centerX")
                y = item.get("y") or item.get("pointY") or item.get("centerY")
                if x is None or y is None:
                    continue
                pos = [x, y]
            try:
                item_pos = (float(pos[0]), float(pos[1]))
            except (TypeError, ValueError):
                continue
            objects.append(
                {
                    "pos": item_pos,
                    "type": (
                        item.get("type")
                        or item.get("name")
                        or item.get("label")
                        or item.get("objectType")
                        or key.rstrip("s")
                    ),
                    "angle": item.get("angle"),
                    "scale": item.get("scale"),
                }
            )
    return objects


def _robot_pos(record: dict, points: list[tuple[float, float]]) -> tuple[float, float] | None:
    pos = record.get("pos")
    if isinstance(pos, list) and len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    return points[-1] if points else None


def _bounds(
    points: list[tuple[float, float]],
    areas: list[dict],
    objects: list[dict],
    robot_pos: tuple[float, float] | None,
) -> tuple[float, float, float, float]:
    all_points = list(points)
    for area in areas:
        all_points.extend(area["points"])
    for item in objects:
        all_points.append(item["pos"])
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
    objects: list[dict],
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

    min_x, max_x, min_y, max_y = _bounds(points, areas, objects, robot_pos)
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

    for item in objects:
        _draw_object(draw, tx(item["pos"]), item["type"])

    if robot_pos:
        _draw_robot(draw, tx(robot_pos), record.get("phi"))

    _draw_stats_panel(draw, record, objects, canvas_w)
    return image


def _map_transform(record: dict) -> dict:
    points = _points_from_record(record)
    areas = _areas_from_record(record)
    objects = _objects_from_record(record)
    robot_pos = _robot_pos(record, points)
    min_x, max_x, min_y, max_y = _bounds(points, areas, objects, robot_pos)
    canvas_w = 1100
    canvas_h = 820
    padding = 70
    span_x = max(max_x - min_x, 1)
    span_y = max(max_y - min_y, 1)
    scale = min((canvas_w - padding * 2) / span_x, (canvas_h - padding * 2) / span_y)
    return {
        "image_width": canvas_w,
        "image_height": canvas_h,
        "padding": padding,
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
        "scale": scale,
    }


def _draw_header(draw: ImageDraw.ImageDraw, record: dict, points: list[tuple[float, float]], title: str) -> None:
    area = _cleaned_area(record)
    map_area = _estimated_area(record)
    duration = record.get("cleanTime")
    source = record.get("source", "record")
    subtitle = (
        f"Quelle: {source}  Geschaetzte Flaeche: {map_area or '?'} m2  "
        f"Gereinigter Bereich: {area or '?'} m2  Zeit: {_minutes(duration) or '?'} min"
    )
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


def _draw_object(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    label: str,
    isometric: bool = False,
) -> None:
    x, y = point
    if isometric:
        draw.ellipse([x - 10, y + 9, x + 10, y + 15], fill="#8a6d3b")
    draw.rectangle([x - 9, y - 9, x + 9, y + 9], fill="#f59e0b", outline="#7c2d12", width=2)
    draw.text((x + 12, y - 8), str(label)[:16], fill="#7c2d12")


def _draw_stats_panel(draw: ImageDraw.ImageDraw, record: dict, objects: list[dict], canvas_w: int) -> None:
    x = canvas_w - 300
    y = 22
    panel = [
        f"Geschaetzte Flaeche: {_estimated_area(record) or '?'} m2",
        f"Gereinigter Bereich: {_cleaned_area(record) or '?'} m2",
        f"Reinigungsdauer: {_minutes(record.get('cleanTime')) or '?'} min",
        f"Abdeckung ca.: {_coverage_percent(record) or '?'} %",
        f"Gegenstaende: {len(objects)}",
        f"Hindernisse erkannt: {record.get('obstaclesTimes', 0)}",
    ]
    draw.rounded_rectangle([x - 16, y - 8, canvas_w - 42, y + 142], radius=12, fill="#ffffff", outline="#dedede")
    for idx, line in enumerate(panel):
        draw.text((x, y + idx * 21), line, fill="#334155")


def _cleaned_area(record: dict) -> int | None:
    area = record.get("cleanArea") or record.get("sweep")
    try:
        return int(round(float(area)))
    except (TypeError, ValueError):
        return None


def _raw_map_area(record: dict) -> int | None:
    width = record.get("width")
    height = record.get("height")
    resolution = record.get("resolution")
    try:
        return int(round(float(width) * float(height) * (float(resolution) ** 2)))
    except (TypeError, ValueError):
        return None


def _estimated_area(record: dict) -> int | None:
    for key in ("estimatedArea", "allArea", "areaTotal"):
        value = record.get(key)
        if value:
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                pass

    # The Android app computes this from libNativeMapJNI.getArea() * 1.8.
    # Until that ARM/Android native code is ported, use a calibrated contour
    # heuristic from the raw map bounding area. This matches S6 records closely
    # enough for display, but is intentionally labelled as approximate.
    raw = _raw_map_area(record)
    if raw is None:
        return None
    return int(round(raw * 0.69))


def _coverage_percent(record: dict) -> int | None:
    cleaned = _cleaned_area(record)
    total = _estimated_area(record)
    if not cleaned or not total:
        return None
    return min(100, int(round(cleaned / total * 100)))


def _minutes(seconds: int | float | None) -> int | None:
    try:
        return int(round(float(seconds) / 60))
    except (TypeError, ValueError):
        return None


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
