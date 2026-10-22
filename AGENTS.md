# 360 Vacuum Robot — HA Custom Component

## Zweck

Home Assistant Custom Component für Qihoo 360 Saugroboter (360 AI CleanRobot S6).

Kein lokaler API-Zugang — ausschließlich über 360 Smart Home Cloud (`q.smart.360.cn`).

## Repo

GitHub: https://github.com/juetthei/ha-360-vacuum (public, MIT)

## Struktur

```
custom_components/vacuum_360/
├── __init__.py        Setup, async_setup_entry, async_unload_entry
├── api.py             API-Client (aiohttp), Commands, GetList
├── coordinator.py     DataUpdateCoordinator, 30s Polling via GetList
├── vacuum.py          StateVacuumEntity, Start/Pause/Return/Stop
├── sensor.py          Akku-Sensor (device_class battery)
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

Zielsystem: Home Assistant mit HACS oder manueller Installation einer Custom Integration.
Es gibt keinen Build-Schritt. Bei manueller Installation den Ordner
`custom_components/vacuum_360` in `<HA-Konfigurationsordner>/custom_components/`
kopieren und Home Assistant neu starten. Konkrete Server, Pfade und Zugangsdaten
gehören ins private Infrastruktur-Repo. Deployment nur auf ausdrücklichen Auftrag.

HA: Einstellungen → Integrationen → "360 Vacuum Robot" hinzufügen.

## Bekannte Offene Punkte

- GetList-Response-Feldnamen unbekannt (verschiedene Firmware-Versionen) → flexibles Parsing eingebaut, Debug-Logging vorhanden
- TCP-Push-Socket (47.254.151.104:443, AES-128-CBC) noch nicht implementiert → aktuell nur Polling
- Auto-Login via passport.360.cn (DES-Encrypt) nicht implementiert (Captcha-Problem)
- Karten-Entity via S3 nicht implementiert

## HA-Kompatibilität

- Minimum: HA 2025.1 (`VacuumActivity` existiert erst ab dieser Version)
- HA 2026.9 hat Batterie aus `VacuumEntityFeature` und `StateVacuumEntity`
  entfernt. Der Akkustand liegt daher seit v1.1.0 in `sensor.py` als eigene
  Entity (`sensor.<name>_battery`) statt als `battery_level`-Attribut.

## Lokale Prüfung und Konventionen

- Python-Syntax: `python3 -m compileall -q custom_components/vacuum_360`
- Whitespace: `git diff --check`
- JSON-Dateien mit `json.loads`, Dashboard-YAML mit `yaml.safe_load_all` prüfen.
- Im aktuellen Arbeitsumfeld ist Home Assistant nicht installiert; Syntax- und
  Formatprüfungen ersetzen keinen Laufzeittest mit HA und einem Roboter.
- Kompatibilitätspatch: https://github.com/juetthei/ha-360-vacuum/pull/2
- `AGENTS.md` ist die gemeinsame Projektanleitung. `CLAUDE.md` und `GEMINI.md`
  sind Symlinks darauf. Keine Zugangsdaten committen; Push nur auf Auftrag.

## Erkenntnisse beim Deployment

- Vorhandene Installationen können vom GitHub-Hauptzweig abweichen. Vor Updates
  sichern und vergleichen; zusätzliche Statusabfrage (`get_status`), Online-Fallback
  und drei Updatezyklen für optimistische Zustände müssen erhalten bleiben.
- Batterie-Sensor, Entity-Setup und bestehende Statusabfrage wurden mit HA 2025.11.1
  isoliert gegen simulierte Daten geprüft. Im Test waren Netzwerkverbindungen gesperrt.
- Bei Updates ohne Roboterbewegung keine Start-/Pause-/Rückkehr-/Suchbefehle testen.
  Vor einem HA-Neustart Automationen auf mögliche Roboteraktionen prüfen.
