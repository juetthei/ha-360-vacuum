"""Start user-confirmed cleaning rectangles saved for an active robot map."""

import asyncio

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store

from .api import Api360, Api360Error
from .const import CLEAN_AREA_MODES, CONF_BLOCKED_START_SNS, CONF_MAP_GUARDS, DOMAIN
from .map_guard import map_guard_state

SERVICE_CLEAN_ZONE = "clean_zone"
ZONE_STORE = "vacuum_360_saved_zones"
SERVICE_SCHEMA = vol.Schema({vol.Required("zone_id"): str})


async def async_start_saved_zone(api: Api360, sn: str, zone: dict, guard: dict) -> None:
    """Validate map and stair protection immediately before sending the command."""
    if not zone.get("confirmed_by_user"):
        raise ServiceValidationError("Reinigungsfläche wurde noch nicht bestätigt")
    try:
        current = await api.get_current_map(sn)
    except Api360Error as exc:
        raise HomeAssistantError("Aktuelle Karte konnte nicht geprüft werden") from exc
    if map_guard_state(current, guard) != "safe":
        raise HomeAssistantError("Sperrzone fehlt oder Karte hat gewechselt")
    if str(current.get("mapId")) != str(zone.get("map_id")):
        raise HomeAssistantError("Gespeicherte Reinigungsfläche gehört zu einer anderen Karte")
    areas = zone.get("areas", [zone])
    if not isinstance(areas, list) or not areas:
        raise ServiceValidationError("Reinigungsfläche enthält keine Rechtecke")
    seen_ids = set()
    for area in areas:
        if not isinstance(area, dict):
            raise ServiceValidationError("Ungültiges Reinigungsrechteck")
        vertices = area.get("vertices")
        if (not isinstance(vertices, list) or len(vertices) != 4
                or any(not isinstance(point, list) or len(point) != 2
                       or any(type(value) is not int for value in point)
                       for point in vertices)):
            raise ServiceValidationError("Reinigungsrechteck hat keine vier gültigen Eckpunkte")
        points = {tuple(point) for point in vertices}
        if (len(points) != 4 or len({x for x, _ in points}) != 2
                or len({y for _, y in points}) != 2):
            raise ServiceValidationError("Reinigungsrechteck ist nicht rechteckig")
        area_id = area.get("source_area_id")
        if (type(area_id) is not int or area_id in seen_ids
                or not isinstance(area.get("source_area_name"), str)):
            raise ServiceValidationError("Reinigungsrechteck hat keine eindeutige Kennung")
        if area.get("active", "normal") not in CLEAN_AREA_MODES:
            raise ServiceValidationError("Unbekannter Modus der Reinigungsfläche")
        seen_ids.add(area_id)
    try:
        status = await api.get_status(sn)
    except Api360Error as exc:
        raise HomeAssistantError("Roboterstatus konnte nicht geprüft werden") from exc
    if status.get("mode") not in {"charge", "fullcharge", "idle", "standby"}:
        raise HomeAssistantError("Roboter ist nicht bereit für eine Zonenreinigung")
    await api.clean_zone(sn, int(current["mapId"]), zone)


async def async_clean_zone(hass: HomeAssistant, call: ServiceCall) -> None:
    data = await Store(hass, 1, ZONE_STORE).async_load()
    zones = (data or {}).get("zones", [])
    zone = next((item for item in zones if item.get("id") == call.data["zone_id"]), None)
    if zone is None:
        raise ServiceValidationError("Reinigungsfläche ist nicht gespeichert")
    sn = zone["sn"]
    for entry in hass.config_entries.async_entries(DOMAIN):
        robot = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get(sn)
        guard = entry.options.get(CONF_MAP_GUARDS, {}).get(sn)
        if robot and guard:
            if sn in entry.options.get(CONF_BLOCKED_START_SNS, []):
                raise HomeAssistantError("Start für diesen Roboter in Home Assistant gesperrt")
            locks = hass.data.setdefault(f"{DOMAIN}_zone_locks", {})
            lock = locks.setdefault(sn, asyncio.Lock())
            if lock.locked():
                raise HomeAssistantError("Reinigungsauftrag läuft bereits an")
            async with lock:
                await async_start_saved_zone(robot.api, sn, zone, guard)
                await robot.async_request_refresh()
            return
    raise ServiceValidationError("Roboter oder Treppensperren-Prüfung nicht verfügbar")
