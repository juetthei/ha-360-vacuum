import json
import logging
import uuid
import aiohttp

from .const import API_BASE, API_CMD, API_DEVICES, DEV_TYPE, INFO_START, INFO_RETURN, INFO_PAUSE, INFO_STATUS

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

    def _common_payload(self, payload: dict | None = None) -> dict:
        """Match the Android app's common POST parameters."""
        data = dict(payload or {})
        data.setdefault("taskid", str(uuid.uuid4()))
        data.setdefault("from", "mpc_and")
        data.setdefault("devType", DEV_TYPE)
        data.setdefault("channel_id", "")
        data.setdefault("appVer", "11.0.0")
        data.setdefault("lang", "de_DE")
        data.setdefault("model", "Home Assistant")
        data.setdefault("manufacturer", "Home Assistant")
        return data

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
                data=self._common_payload(),
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
                data=self._common_payload(payload),
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

    async def start_point(self, sn: str, x: int, y: int) -> None:
        await self.send_cmd(sn, INFO_START, {"mode": "givenPoint", "point": [int(x), int(y)]})

    async def start_rooms(self, sn: str, area_ids: list[int]) -> None:
        await self.send_cmd(sn, INFO_START, {"mode": "areaClean", "areaId": [int(area_id) for area_id in area_ids]})

    async def return_to_base(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_RETURN, {"cmd": "start"})

    async def pause(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_PAUSE, {"cmd": "pause"})

    async def resume(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_PAUSE, {"cmd": "continue"})

    async def get_status(self, sn: str) -> dict:
        return await self.send_cmd(sn, INFO_STATUS)

    async def get_clean_map(self, sn: str) -> dict:
        """Return live map data when the robot exposes it through cmd/send."""
        return await self.send_cmd(sn, "20002")

    async def get_clean_path(self, sn: str, start_pos: int = 0) -> dict:
        """Return live path data when the robot exposes it through cmd/send."""
        return await self.send_cmd(
            sn,
            "21011",
            {"startPos": start_pos, "userId": "0", "mask": 0},
        )

    async def get_live_clean_snapshot(self, sn: str) -> dict | None:
        """Return live cleaning map/path/status data, if currently available."""
        status = await self.get_status(sn)
        map_data = await self.get_clean_map(sn)
        path_data = await self.get_clean_path(sn)

        if not (status or map_data or path_data):
            return None

        snapshot = {**map_data, **status}
        pos_array = path_data.get("posArray") or snapshot.get("posArray")
        if pos_array:
            snapshot["posArray"] = pos_array
        elif not map_data.get("map") and not status.get("pos"):
            return None

        snapshot["source"] = "live"
        snapshot["cleanId"] = "live"
        return snapshot

    async def get_clean_records(self, sn: str, page_size: int = 5) -> list[dict]:
        """Return recent cleaning records."""
        payload = self._common_payload({"sn": sn, "lastId": "", "pageSize": str(page_size)})
        try:
            async with self._session.post(
                f"{API_BASE}/clean/record/getList",
                headers=self._headers(),
                data=payload,
                timeout=_TIMEOUT,
            ) as resp:
                result = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise Api360Error(f"Netzwerkfehler beim Abrufen der Reinigungsdaten: {exc}") from exc

        _LOGGER.debug("Record getList response: %s", result)
        self._check_errno(result, "record/getList")
        data = result.get("data") or {}
        records = data.get("list") or data.get("records") or []
        return records if isinstance(records, list) else []

    async def get_clean_record(self, sn: str, clean_id: str) -> dict:
        """Return a single cleaning record including map/path data."""
        payload = self._common_payload({"sn": sn, "cleanId": clean_id})
        try:
            async with self._session.post(
                f"{API_BASE}/clean/record/getOne",
                headers=self._headers(),
                data=payload,
                timeout=_TIMEOUT,
            ) as resp:
                result = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise Api360Error(f"Netzwerkfehler beim Abrufen der Karte: {exc}") from exc

        _LOGGER.debug("Record getOne response keys: %s", list((result.get("data") or {}).keys()))
        self._check_errno(result, "record/getOne")
        data = result.get("data") or {}
        return data.get("record") or data

    async def get_latest_clean_record(self, sn: str) -> dict | None:
        """Return the newest record that contains map/path data."""
        for item in await self.get_clean_records(sn):
            clean_id = item.get("cleanId")
            if not clean_id:
                continue
            record = await self.get_clean_record(sn, clean_id)
            if record.get("posArray") or record.get("map"):
                if not record.get("cleanId"):
                    record["cleanId"] = clean_id
                return record
        return None
