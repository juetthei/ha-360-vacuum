import logging
from datetime import timedelta
import json
import time
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Api360, Api360AuthError, Api360Error
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

_EXTERNAL_STATUS_MAX_AGE = 10 * 60


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
        self._external_status_file = Path(hass.config.path(".storage", f"vacuum_360_status_{sn}.json"))

    def _get_external_status(self) -> dict:
        """Read optional status captured from the Android app/push channel."""
        try:
            payload = json.loads(self._external_status_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

        if payload.get("sn") not in (None, self.sn):
            return {}

        updated_at = payload.get("updated_at")
        try:
            age = time.time() - float(updated_at)
        except (TypeError, ValueError):
            return {}

        if age < 0 or age > _EXTERNAL_STATUS_MAX_AGE:
            return {}

        status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
        if not status:
            status = {key: value for key, value in payload.items() if key not in ("sn", "updated_at", "status")}
        if not status:
            return {}

        status["external_status_source"] = payload.get("source", "external_status_cache")
        status["external_status_age"] = round(age)
        return status

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
            live_status = await self.api.get_status(self.sn)
            if live_status:
                dev["live_status"] = live_status
                dev.update(_extract_status(live_status))
        except Api360Error as exc:
            _LOGGER.debug("Live-Status fuer %s nicht verfuegbar: %s", self.sn, exc)

        external_status = self._get_external_status()
        if external_status:
            dev["external_status"] = external_status
            dev.update(_extract_status(external_status))

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
