import logging
from datetime import timedelta
import json

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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


def _parse_support_flags(dev: dict) -> dict[str, bool]:
    raw = dev.get("support") or dev.get("supportFlags") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): bool(value) for key, value in raw.items()}


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
        self._stats_cache: dict = {}
        self._recent_cache: dict = {}
        self._stats_last_update = None

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

        dev["support_flags"] = _parse_support_flags(dev)

        try:
            dev["consumables"] = await self.api.get_consumables(self.sn)
        except Api360Error as exc:
            _LOGGER.debug("Verbrauchsdaten fuer %s nicht verfuegbar: %s", self.sn, exc)
            dev["consumables"] = (self.data or {}).get("consumables", {})

        now = dt_util.utcnow()
        if (
            not self._stats_last_update
            or now - self._stats_last_update > timedelta(minutes=5)
            or not self._stats_cache
        ):
            try:
                self._stats_cache = await self.api.get_statistics(self.sn)
            except Api360Error as exc:
                _LOGGER.debug("Statistik fuer %s nicht verfuegbar: %s", self.sn, exc)
            try:
                self._recent_cache = await self.api.get_recently_clean_stats(self.sn)
            except Api360Error as exc:
                _LOGGER.debug("Kurzstatistik fuer %s nicht verfuegbar: %s", self.sn, exc)
            self._stats_last_update = now

        dev["statistics"] = self._stats_cache
        dev["recent_stats"] = self._recent_cache

        _LOGGER.debug("Status %s: %s", self.sn, dev)
        return dev
