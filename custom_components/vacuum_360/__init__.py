import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import Api360, Api360AuthError, Api360Error
from .const import CONF_QID, CONF_SID, DOMAIN
from .coordinator import Robot360Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["vacuum", "camera", "sensor", "switch", "number", "button"]

_SERVICE_CLEAN_POINT = "clean_point"
_SERVICE_CLEAN_ROOMS = "clean_rooms"
_SERVICE_EDGE_CLEAN = "edge_clean"
_SERVICE_POINT_CLEAN = "point_clean"
_SERVICE_QUICK_MAPPING = "quick_mapping"
_SERVICE_RESET_CONSUMABLE = "reset_consumable"
_SERVICE_REBOOT = "reboot"


def _service_schema(extra: dict) -> vol.Schema:
    return vol.Schema({vol.Optional("sn"): cv.string, **extra})


def _first_or_matching_coordinator(hass: HomeAssistant, sn: str | None) -> Robot360Coordinator:
    for coordinators in hass.data.get(DOMAIN, {}).values():
        for coord_sn, coord in coordinators.items():
            if sn is None or coord_sn == sn:
                return coord
    raise ValueError(f"Kein 360-Sauger fuer sn={sn!r} gefunden")


def _sn_from_device(dev: dict) -> str | None:
    for key in ("sn", "devSn", "deviceSn", "cleanSn"):
        if dev.get(key):
            return dev[key]
    return None


def _name_from_device(dev: dict, sn: str) -> str:
    for key in ("name", "title", "devName", "deviceName", "cleanName"):
        if dev.get(key):
            return dev[key]
    return f"360 Robot {sn[-4:]}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    api = Api360(session, entry.data[CONF_QID], entry.data[CONF_SID])

    try:
        devices = await api.get_devices()
    except Api360AuthError as exc:
        raise ConfigEntryAuthFailed(str(exc)) from exc
    except Api360Error as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    coordinators: dict[str, Robot360Coordinator] = {}
    for dev in devices:
        sn = _sn_from_device(dev)
        if not sn:
            _LOGGER.warning("Gerät ohne SN übersprungen: %s", dev)
            continue
        name = _name_from_device(dev, sn)
        coord = Robot360Coordinator(hass, api, sn, name)
        try:
            await coord.async_config_entry_first_refresh()
        except Exception:
            _LOGGER.warning("Erster Refresh für %s fehlgeschlagen, fahre fort", sn)
        coordinators[sn] = coord

    if not coordinators:
        raise ConfigEntryNotReady("Keine Geräte mit gültiger Seriennummer gefunden")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators
    _register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _register_services(hass: HomeAssistant) -> None:
    async def handle_clean_point(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.start_point(coord.sn, call.data["x"], call.data["y"])
        await coord.async_request_refresh()

    async def handle_clean_rooms(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.start_rooms(coord.sn, call.data["area_ids"])
        await coord.async_request_refresh()

    async def handle_edge_clean(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.edge_clean(coord.sn)
        await coord.async_request_refresh()

    async def handle_point_clean(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.point_clean(coord.sn, call.data.get("count", 2), call.data.get("style", 0))
        await coord.async_request_refresh()

    async def handle_quick_mapping(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.quick_mapping(coord.sn)
        await coord.async_request_refresh()

    async def handle_reset_consumable(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.reset_consumable(coord.sn, call.data["material"])
        await coord.async_request_refresh()

    async def handle_reboot(call) -> None:
        coord = _first_or_matching_coordinator(hass, call.data.get("sn") or None)
        await coord.api.reboot(coord.sn)
        await coord.async_request_refresh()

    services = {
        _SERVICE_CLEAN_POINT: (
            handle_clean_point,
            _service_schema({vol.Required("x"): vol.Coerce(int), vol.Required("y"): vol.Coerce(int)}),
        ),
        _SERVICE_CLEAN_ROOMS: (
            handle_clean_rooms,
            _service_schema({vol.Required("area_ids"): vol.All(cv.ensure_list, [vol.Coerce(int)])}),
        ),
        _SERVICE_EDGE_CLEAN: (
            handle_edge_clean,
            _service_schema({}),
        ),
        _SERVICE_POINT_CLEAN: (
            handle_point_clean,
            _service_schema({vol.Optional("count", default=2): vol.Coerce(int), vol.Optional("style", default=0): vol.Coerce(int)}),
        ),
        _SERVICE_QUICK_MAPPING: (
            handle_quick_mapping,
            _service_schema({}),
        ),
        _SERVICE_RESET_CONSUMABLE: (
            handle_reset_consumable,
            _service_schema({vol.Required("material"): vol.In(["filter", "mainBrush", "sideBrush", "sensors"])}),
        ),
        _SERVICE_REBOOT: (
            handle_reboot,
            _service_schema({}),
        ),
    }

    for service, (handler, schema) in services.items():
        if not hass.services.has_service(DOMAIN, service):
            hass.services.async_register(DOMAIN, service, handler, schema=schema)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
