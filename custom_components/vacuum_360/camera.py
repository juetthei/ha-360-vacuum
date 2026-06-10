from __future__ import annotations

import io
import logging
import math
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFilter

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
    objects = _objects_from_record(record)
    robot_pos = _robot_pos(record, points)

    if mode == "3d":
        return _png_bytes(_render_isometric(record, points, areas, objects, robot_pos))
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
    for key in ("furniture", "objects", "obstacles"):
        for item in record.get(key) or []:
            pos = item.get("pos") or item.get("position")
            if not isinstance(pos, list) or len(pos) < 2:
                continue
            objects.append(
                {
                    "pos": (float(pos[0]), float(pos[1])),
                    "type": item.get("type") or item.get("name") or key.rstrip("s"),
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


def _render_isometric(
    record: dict,
    points: list[tuple[float, float]],
    areas: list[dict],
    objects: list[dict],
    robot_pos: tuple[float, float] | None,
) -> Image.Image:
    canvas_w = 1100
    canvas_h = 820
    padding = 80
    image = Image.new("RGB", (canvas_w, canvas_h), "#f7f7f7")
    draw = ImageDraw.Draw(image)

    if not points and not areas:
        draw.text((padding, padding), "Keine Kartendaten verfuegbar", fill="#334155")
        return image

    min_x, max_x, min_y, max_y = _bounds(points, areas, objects, robot_pos)
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    projected = [_iso(point, cx, cy) for point in points]
    for area in areas:
        projected.extend(_iso(point, cx, cy) for point in area["points"])
    projected.extend(_iso(item["pos"], cx, cy) for item in objects)
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
            _draw_extruded_polygon(draw, mapped_area, "#f7f7f7")

    if len(points) > 1:
        mapped = [tx(point) for point in points]
        floor_mask = _draw_app_style_floor(image, draw, mapped)
        _draw_app_style_walls(draw, floor_mask)
        _draw_marker(draw, mapped[0], "#22c55e")
        _draw_marker(draw, mapped[-1], "#ef4444")

    for item in objects:
        x, y = tx(item["pos"])
        _draw_object(draw, (x, y - 12), item["type"], isometric=True)

    if robot_pos:
        _draw_robot(draw, tx(robot_pos), record.get("phi"), radius=14)

    _draw_stats_panel(draw, record, objects, canvas_w)
    return image


def _iso(point: tuple[float, float], cx: float, cy: float) -> tuple[float, float]:
    x, y = point
    x -= cx
    y -= cy
    return (x - y) * 0.72, (x + y) * 0.36


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


def _draw_app_style_floor(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    mapped: list[tuple[int, int]],
) -> Image.Image:
    # App-like cleaned floor: merge the driven path into one warm surface and
    # draw the actual cleaning route as fine white lines on top.
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.line(mapped, fill=255, width=54, joint="curve")
    mask = mask.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(2))

    floor = Image.new("RGB", image.size, "#cfc4b6")
    image.paste(floor, (0, 0), mask)

    shadow = Image.new("L", image.size, 0)
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.line([(x, y + 18) for x, y in mapped], fill=90, width=62, joint="curve")
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    shadow_layer = Image.new("RGB", image.size, "#b7aca0")
    image.paste(shadow_layer, (0, 0), shadow)
    image.paste(floor, (0, 0), mask)

    for offset in range(-10, 12, 5):
        draw.line([(x, y + offset) for x, y in mapped], fill="#ffffff", width=2, joint="curve")

    step = max(1, len(mapped) // 120)
    for idx in range(0, len(mapped), step):
        x, y = mapped[idx]
        draw.line([(x - 18, y + 10), (x + 30, y - 2)], fill="#b9ad9e", width=1)

    return mask


def _draw_app_style_walls(draw: ImageDraw.ImageDraw, floor_mask: Image.Image) -> None:
    # Approximate the app's extruded white/grey wall blocks from the floor mask
    # boundary. The exact wall contours require the proprietary map decoder.
    edge = floor_mask.filter(ImageFilter.FIND_EDGES).point(lambda value: 255 if value > 12 else 0)
    width, height = edge.size
    pixels = edge.load()
    columns: dict[int, tuple[int, int]] = {}
    bucket = 10
    for x in range(0, width, 2):
        ys = [y for y in range(70, height - 60, 2) if pixels[x, y]]
        if not ys:
            continue
        key = (x // bucket) * bucket
        top = min(ys)
        bottom = max(ys)
        current = columns.get(key)
        if current is None:
            columns[key] = (top, bottom)
        else:
            columns[key] = (min(current[0], top), max(current[1], bottom))

    wall_tops = []
    for idx, (x, (top, bottom)) in enumerate(sorted(columns.items())):
        if idx % 2:
            continue
        height_px = 54 if idx % 4 else 72
        draw.line([(x, top + 8), (x, top - height_px)], fill="#d5d5d5", width=5)
        draw.line([(x + 3, top + 6), (x + 3, top - height_px + 2)], fill="#ffffff", width=7)
        wall_tops.append((x + 3, top - height_px + 2))
        if idx % 5 == 0:
            draw.line([(x, bottom - 4), (x, bottom - 34)], fill="#e0e0e0", width=4)

    if len(wall_tops) > 1:
        draw.line(wall_tops, fill="#eeeeee", width=5, joint="curve")


def _draw_extruded_polygon(draw: ImageDraw.ImageDraw, polygon: list[tuple[int, int]], top_color: str) -> None:
    for height, color in ((55, "#dadada"), (38, "#ededed"), (18, "#ffffff")):
        shifted = [(x, y - height) for x, y in polygon]
        for start, end in zip(polygon, polygon[1:] + polygon[:1]):
            wall = [start, end, (end[0], end[1] - height), (start[0], start[1] - height)]
            draw.polygon(wall, fill=color)
        draw.polygon(shifted, fill=top_color, outline="#d8d8d8")


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
