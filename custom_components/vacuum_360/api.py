import json
import logging
import aiohttp

from .const import API_CMD, API_DEVICES, DEV_TYPE, INFO_START, INFO_RETURN, INFO_PAUSE, INFO_STATUS

_LOGGER = logging.getLogger(__name__)

# Fester Wert aus dem App-Traffic (q-Cookie bleibt unveränderlich)
_COOKIE_Q = "u=&t=1;t=&v=2.0&a=1"

_BASE_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Connection":   "Keep-Alive",
    "Accept-Encoding": "gzip",
    "User-Agent":   "okhttp/4.9.3",
}

_TIMEOUT = aiohttp.ClientTimeout(total=15)


class Api360Error(Exception):
    pass


class Api360AuthError(Api360Error):
    """SID abgelaufen oder ungültig."""


class Api360:
    def __init__(self, session: aiohttp.ClientSession, qid: str, sid: str) -> None:
        self._session = session
        self.qid = qid
        self.sid = sid

    def _headers(self) -> dict:
        return {
            **_BASE_HEADERS,
            "Cookie": f"q={_COOKIE_Q}; qid={self.qid}; sid={self.sid}",
        }

    def _check_errno(self, result: dict, label: str) -> None:
        errno = result.get("errno", -1)
        if errno == 0:
            return
        msg = result.get("errmsg", "unknown")
        # Typische Auth-Fehlercodes der 360-Cloud
        if errno in (401, 403, -2, 10001, 10002):
            raise Api360AuthError(f"{label}: auth error ({errno}) – {msg}")
        raise Api360Error(f"{label}: errno={errno} – {msg}")

    async def get_devices(self) -> list[dict]:
        """Geräteliste aus der 360-Cloud holen."""
        try:
            async with self._session.post(
                API_DEVICES,
                headers=self._headers(),
                data="devType=3",
                timeout=_TIMEOUT,
            ) as resp:
                result = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise Api360Error(f"Netzwerkfehler beim Abrufen der Geräte: {exc}") from exc

        _LOGGER.debug("GetList response: %s", result)
        self._check_errno(result, "GetList")

        data = result.get("data", {})
        if isinstance(data, list):
            return data
        # Varianten: devList, list, devices
        for key in ("devList", "list", "devices", "cleanDevList"):
            if key in data:
                return data[key]
        return []

    async def send_cmd(self, sn: str, info_type: str, data: dict | None = None) -> dict:
        payload: dict = {"sn": sn, "infoType": info_type, "devType": DEV_TYPE}
        if data is not None:
            payload["data"] = json.dumps(data, separators=(",", ":"))

        try:
            async with self._session.post(
                API_CMD,
                headers=self._headers(),
                data=payload,
                timeout=_TIMEOUT,
            ) as resp:
                result = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise Api360Error(f"Netzwerkfehler bei Befehl {info_type}: {exc}") from exc

        _LOGGER.debug("Cmd %s sn=%s response: %s", info_type, sn, result)
        self._check_errno(result, f"cmd/{info_type}")
        return result.get("data") or {}

    async def start(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_START, {"mode": "smartClean", "globalCleanTimes": 1})

    async def return_to_base(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_RETURN, {"cmd": "start"})

    async def pause(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_PAUSE, {"cmd": "pause"})

    async def resume(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_PAUSE, {"cmd": "continue"})

    async def get_status(self, sn: str) -> dict:
        return await self.send_cmd(sn, INFO_STATUS)
