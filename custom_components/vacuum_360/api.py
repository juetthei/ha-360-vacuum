import asyncio
import json
import logging
import uuid

import aiohttp
from botslab360.exceptions import ApiError
from botslab360.protocol import PushClient

from .const import (
    API_CMD, API_DEVICES, DEV_TYPE, INFO_FAN_SPEED, INFO_LOCATE, INFO_SETTINGS, INFO_START, INFO_RETURN, INFO_PAUSE, INFO_STATUS,
)

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

_MAP_LOAD_DATA = {
    "cmds": [
        {"infoType": "20001", "data": {}},
        {"infoType": "21014", "data": {}},
        {"infoType": "21011", "data": {"startPos": 0, "userId": 0, "mask": 0}},
    ],
    "mainCmds": [],
}


class Api360Error(Exception):
    pass


class Api360AuthError(Api360Error):
    """SID abgelaufen oder ungültig."""


class Api360:
    def __init__(
        self, session: aiohttp.ClientSession, qid: str, sid: str, pushkey: str | None = None
    ) -> None:
        self._session = session
        self.qid = qid
        self.sid = sid
        self.pushkey = pushkey

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

    async def get_latest_clean_record(self, sn: str) -> dict | None:
        """Read the latest completed cleaning map, without sending robot commands."""
        async def post(path: str, payload: dict) -> dict:
            data = {
                "sn": sn,
                "devType": DEV_TYPE,
                "from": "mpc_and",
                "taskid": str(uuid.uuid4()),
                "appVer": "11.0.0",
                "lang": "de_DE",
                **payload,
            }
            try:
                async with self._session.post(
                    f"https://q.smart.360.cn{path}",
                    headers=self._headers(),
                    data=data,
                    timeout=_TIMEOUT,
                ) as resp:
                    result = await resp.json(content_type=None)
            except aiohttp.ClientError as exc:
                raise Api360Error("Reinigungsaufzeichnung nicht erreichbar") from exc
            self._check_errno(result, path)
            return result.get("data") or {}

        listing = await post("/clean/record/getList", {"lastId": "", "pageSize": "5"})
        for item in (listing.get("list") or listing.get("records") or []):
            if not item.get("cleanId"):
                continue
            record = await post("/clean/record/getOne", {"cleanId": item["cleanId"]})
            record = record.get("record") or record
            if record.get("map") and record.get("width") and record.get("height"):
                return record
        return None

    async def get_current_map(self, sn: str) -> dict:
        """Read the robot's active map, including its current forbidden areas."""
        if not self.pushkey:
            raise Api360Error("Push-Schlüssel für aktuelle Karte fehlt")
        try:
            async with PushClient(self.sid, self.pushkey) as push:
                await self.send_cmd(sn, "30000", _MAP_LOAD_DATA)
                async with asyncio.timeout(25):
                    while True:
                        event = await push.read_event()
                        if event.get("sn") != sn:
                            continue
                        body = event.get("data")
                        if isinstance(body, str):
                            body = json.loads(body)
                        if not isinstance(body, dict) or str(body.get("infoType")) != "20002":
                            continue
                        map_data = body.get("data")
                        if isinstance(map_data, str):
                            map_data = json.loads(map_data)
                        if isinstance(map_data, dict) and map_data.get("map"):
                            return map_data
        except (ApiError, aiohttp.ClientError, OSError, TimeoutError, ValueError) as exc:
            raise Api360Error("Aktuelle Karte konnte nicht abgerufen werden") from exc

    async def start(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_START, {"mode": "smartClean", "globalCleanTimes": 1})

    async def clean_zone(self, sn: str, map_id: int, zone: dict) -> None:
        """Start cleaning all rectangles in one saved area on the active map."""
        areas = [{
            "vertexs": item["vertices"],
            "active": item.get("active", "normal"),
            "name": item["source_area_name"],
            "tag": "",
            "id": item["source_area_id"],
            "mode": "default",
        } for item in zone.get("areas", [zone])]
        await self.send_cmd(sn, "30000", {
            "cmds": [
                {"infoType": "21023", "data": {
                    "mapId": map_id, "cleanId": [-2], "extraAreas": areas,
                }},
                {"infoType": "21005", "data": {"mode": "reAppointClean"}},
            ],
            "mainCmds": ["21005"],
        })

    async def return_to_base(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_RETURN, {"cmd": "start"})

    async def pause(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_PAUSE, {"cmd": "pause"})

    async def resume(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_PAUSE, {"cmd": "continue"})

    async def set_fan_speed(self, sn: str, mode: str) -> None:
        await self.send_cmd(sn, INFO_FAN_SPEED, {"cmd": mode})

    async def locate(self, sn: str) -> None:
        await self.send_cmd(sn, INFO_LOCATE, {"ctrlCode": 3010})

    async def set_volume(self, sn: str, level: int) -> None:
        # 21024 trägt auch Neustart und Karte löschen: nur exakt setVolume mit 0–10 senden.
        if not isinstance(level, int) or not 0 <= level <= 10:
            raise Api360Error(f"Ungültige Lautstärkestufe: {level}")
        await self.send_cmd(sn, INFO_SETTINGS, {"cmd": "setVolume", "value": level})

    async def get_status(self, sn: str) -> dict:
        if not self.pushkey:
            return await self.send_cmd(sn, INFO_STATUS)

        task_id = str(uuid.uuid4())
        payload = {
            "sn": sn,
            "infoType": INFO_STATUS,
            "devType": DEV_TYPE,
            "data": "",
            "taskid": task_id,
            "from": "mpc_and",
            "appVer": "11.0.0",
            "lang": "de_DE",
        }
        try:
            async with PushClient(self.sid, self.pushkey) as push:
                async with self._session.post(
                    API_CMD, headers=self._headers(), data=payload, timeout=_TIMEOUT
                ) as resp:
                    result = await resp.json(content_type=None)
                self._check_errno(result, "status")
                async with asyncio.timeout(25):
                    while True:
                        status = _status_from_push(await push.read_event(), sn, task_id)
                        if status is not None:
                            return status
        except (ApiError, aiohttp.ClientError, OSError, TimeoutError, ValueError) as exc:
            raise Api360Error("Push-Status konnte nicht abgerufen werden") from exc


def _status_from_push(event: dict, sn: str, task_id: str) -> dict | None:
    if event.get("sn") != sn or event.get("taskid") != task_id:
        return None
    body = event.get("data")
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict) or str(body.get("infoType")) != INFO_STATUS:
        return None
    status = body.get("data")
    if isinstance(status, str):
        status = json.loads(status)
    return status if isinstance(status, dict) else None
