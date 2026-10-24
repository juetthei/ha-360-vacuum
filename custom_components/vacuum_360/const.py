DOMAIN = "vacuum_360"

API_BASE = "https://q.smart.360.cn"
API_CMD = f"{API_BASE}/clean/cmd/send"
API_DEVICES = f"{API_BASE}/common/dev/GetList"

INFO_STATUS = "20001"
INFO_START = "21005"
INFO_RETURN = "21012"
INFO_PAUSE = "21017"
INFO_FAN_SPEED = "21022"
INFO_LOCATE = "21020"
INFO_SETTINGS = "21024"

# In der App beobachtete Modi gezeichneter Reinigungsflächen
CLEAN_AREA_MODES = ("normal", "depth")

DEV_TYPE = "3"
SCAN_INTERVAL = 30

CONF_QID = "qid"
CONF_SID = "sid"
CONF_PUSHKEY = "pushkey"
CONF_BLOCKED_START_SNS = "blocked_start_sns"
CONF_MAP_GUARDS = "map_guards"

# HA-Saugstärke → 360-Statusfeld workNoisy / Befehl 21022
FAN_SPEEDS: dict[str, str] = {
    "Leise":    "quiet",
    "Standard": "auto",
    "Power":    "strong",
}

MANUFACTURER = "Qihoo 360"
MODEL = "360 AI CleanRobot S6"

# 360-Cloud-Modusnamen → HA VacuumActivity
MODE_MAP: dict[str, str] = {
    "charge":      "docked",
    "charging":    "docked",
    "fullcharge":  "docked",
    "smartClean":  "cleaning",
    "sweep":       "cleaning",
    "reAppointClean": "cleaning",
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
