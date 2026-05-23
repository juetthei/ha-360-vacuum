DOMAIN = "vacuum_360"

API_BASE = "https://q.smart.360.cn"
API_CMD = f"{API_BASE}/clean/cmd/send"
API_DEVICES = f"{API_BASE}/common/dev/GetList"

INFO_STATUS = "20001"
INFO_START = "21005"
INFO_RETURN = "21012"
INFO_PAUSE = "21017"

DEV_TYPE = "3"
SCAN_INTERVAL = 30

CONF_QID = "qid"
CONF_SID = "sid"

# 360-Cloud-Modusnamen → HA VacuumActivity
MODE_MAP: dict[str, str] = {
    "charge":      "docked",
    "charging":    "docked",
    "smartClean":  "cleaning",
    "aroundClean": "cleaning",
    "spotClean":   "cleaning",
    "totalClean":  "cleaning",
    "pause":       "paused",
    "idle":        "idle",
    "standby":     "idle",
    "chargeback":  "returning",
    "return":      "returning",
    "gocharge":    "returning",
    "error":       "error",
}
