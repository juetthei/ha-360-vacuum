# 360 Vacuum Robot — HA Custom Component

## Zweck

Home Assistant Custom Component für Qihoo 360 Saugroboter (360 AI CleanRobot S6).
Zwei Geräte im Heimnetz: 192.168.178.50 und 192.168.178.51.

Kein lokaler API-Zugang — ausschließlich über 360 Smart Home Cloud (`q.smart.360.cn`).

## Repo

GitHub: https://github.com/juetthei/ha-360-vacuum (public, MIT)
Lokal: /home/server/Projekte/claude/360s6/

## Struktur

```
custom_components/vacuum_360/
├── __init__.py        Setup, async_setup_entry, async_unload_entry
├── api.py             API-Client (aiohttp), Commands, GetList
├── coordinator.py     DataUpdateCoordinator, 30s Polling via GetList
├── vacuum.py          StateVacuumEntity, Start/Pause/Return/Stop/Batterie
├── config_flow.py     ConfigFlow (QID+SID), ReauthFlow
├── const.py           URLs, infoTypes, MODE_MAP
├── manifest.json
├── strings.json
└── translations/de.json, en.json
dashboard_example.yaml  Lovelace-Karten (nur eingebaute HA-Karten)
```

## API-Details

- **Base URL:** `https://q.smart.360.cn`
- **Auth:** Cookie `q=u=&t=1;t=&v=2.0&a=1; qid={qid}; sid={sid}`
- **Geräte:** `POST /common/dev/GetList` → SN, Name, Status
- **Befehle:** `POST /clean/cmd/send` mit `sn`, `infoType`, `data`, `devType=3`

| Funktion       | infoType | data                                          |
|----------------|----------|-----------------------------------------------|
| Start          | 21005    | `{"mode":"smartClean","globalCleanTimes":1}`  |
| Zur Basis      | 21012    | `{"cmd":"start"}`                             |
| Pause          | 21017    | `{"cmd":"pause"}`                             |
| Fortsetzen     | 21017    | `{"cmd":"continue"}`                          |
| Status abrufen | 20001    | —                                             |

## Credentials extrahieren (Android + ADB)

```bash
adb logcat | grep MyPushMessageListener
# → pushkey:... qid:... sid:...
```

SID läuft ca. alle 12h ab → Reauth-Flow in HA greift automatisch.

## HA-Installation

```bash
sudo cp -r custom_components/vacuum_360 \
  /data/compose/70/homeassistent/homeassistant-stack/config/custom_components/
docker restart homeassistant
```

HA: Einstellungen → Integrationen → "360 Vacuum Robot" hinzufügen.

## Bekannte Offene Punkte

- GetList-Response-Feldnamen unbekannt (verschiedene Firmware-Versionen) → flexibles Parsing eingebaut, Debug-Logging vorhanden
- TCP-Push-Socket (47.254.151.104:443, AES-128-CBC) noch nicht implementiert → aktuell nur Polling
- Auto-Login via passport.360.cn (DES-Encrypt) nicht implementiert (Captcha-Problem)
- Karten-Entity via S3 nicht implementiert
