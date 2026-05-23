import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Api360, Api360AuthError, Api360Error
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _extract_status(dev: dict) -> dict:
    """Statusfelder aus verschiedenen möglichen API-Response-Strukturen extrahieren."""
    # Status kann direkt im Device-Objekt oder in einem Unterfeld liegen
    for key in ("devStatus", "status", "cleanStatus", "robotStatus"):
        if key in dev and isinstance(dev[key], dict):
            return {**dev, **dev[key]}
    return dev


def _find_device(devices: list[dict], sn: str) -> dict | None:
    for dev in devices:
        dev_sn = dev.get("sn") or dev.get("devSn") or dev.get("deviceSn") or dev.get("cleanSn")
        if dev_sn == sn:
            return _extract_status(dev)
    return None


class Robot360Coordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, api: Api360, sn: str, name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{sn}",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self.sn = sn
        self.device_name = name

    async def _async_update_data(self) -> dict:
        try:
            devices = await self.api.get_devices()
        except Api360AuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except Api360Error as exc:
            raise UpdateFailed(str(exc)) from exc

        dev = _find_device(devices, self.sn)
        if dev is None:
            _LOGGER.warning("Gerät %s nicht in GetList gefunden, halte letzten Stand", self.sn)
            return self.data or {}

        _LOGGER.debug("Status %s: %s", self.sn, dev)
        return dev
