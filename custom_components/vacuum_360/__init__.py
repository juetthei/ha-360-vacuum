import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import Api360, Api360AuthError, Api360Error
from .const import CONF_QID, CONF_SID, DOMAIN
from .coordinator import Robot360Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["vacuum", "camera"]


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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
