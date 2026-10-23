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
├── camera.py          Aktueller Grundriss + Sperrzonen, optionale letzte Fahrspur
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
- Nach Installation unter HA 2025.11.1 wurden beide Batteriesensoren registriert,
  zeigten aber `unknown`; die Registrierung allein bestätigt keinen gelieferten
  Akkustand. Vor weiteren Batterie-Fixes die tatsächlichen Statusfelder prüfen.
- HA kann Sensor-Entity-IDs übersetzen (z. B. Suffix `_batterie`). Die IDs aus der
  Entity-Registry verwenden, nicht blind die englischen README-Beispiele übernehmen.

## Diagnose der fehlenden Batteriewerte

- Direkte Statusabfrage `20001`, dieselbe Abfrage mit App-Parametern und eine
  `30000`-Sammelabfrage mit ausschließlich `20001` lieferten bei beiden Geräten
  `errno: 0` und `data: {}`. GetList enthält keine Batteriefelder. Die HTTP-Antwort
  bestätigt nur die Anfrage; sie enthält hier keinen Live-Status.
- Der Live-Status wird über den separaten TCP-Push-Kanal übertragen. Zum
  Entschlüsseln wird der zur SID gehörende `pushKey` benötigt. Die bisherige
  Integration speichert nur QID/SID und implementiert keinen Push-Empfang.
- Ein weiterer HTTP-Fallback oder ein geschätzter Akkustand löst das Problem nicht.
  Nächster Schritt: Push-Schlüssel sicher aus derselben App-Anmeldung beschaffen,
  dann Push-Empfang implementieren und echte Batterieupdates nachweisen.
- Protokollreferenzen: `TA2k/ioBroker.botslab360/lib/china.js` und
  `placix/python-botslab360/src/botslab360/protocol.py` auf GitHub. Letzteres
  berücksichtigt TCP-Fragmentierung, Bind-Bestätigung, AES-CBC und das Statusfeld
  `elecReal`. Keine vollständigen Push-Nachrichten oder Schlüssel protokollieren.

## Push-Status und Batterie

- Ab Version 1.2.0 wird `botslab360==0.7.1` für den verschlüsselten Push-Empfang
  benötigt. Der zur SID gehörende `pushkey` wird als geheimes Feld im HA-Config-Entry
  gespeichert und bei Reauth zusammen mit der SID erneuert.
- `Api360.get_status` verbindet sich vor der reinen Statusabfrage `20001` mit
  dem Push-Kanal, gleicht Seriennummer und Task-ID ab und liefert u. a.
  `elecReal` an den Batterie-Sensor. `fullcharge` wird als `docked` angezeigt.
- Live geprüft: beide Geräte meldeten über den neuen Code `elecReal: 100` und
  `mode: fullcharge`; dabei wurde kein Start-, Rückkehr- oder Tonbefehl gesendet.
- Isolationstest: `python -m unittest discover -s tests` in einer Umgebung mit
  Home Assistant und der Manifest-Abhängigkeit. Der Test nutzt nur Mock-Antworten.
- Produktiv nach Installation von v1.2.0 auf HA 2025.11.1: beide Batterie-Sensoren
  zeigen 100 %, beide Vacuum-Entities `docked`, HA HTTP 200, keine relevanten
  Startfehler. Temporäre Schlüsseldateien wurden entfernt; der Push-Schlüssel
  liegt nur im HA-Config-Entry. Integrations- und Config-Entry-Backups liegen
  geschützt auf dem Zielsystem.

## Historische Kartenbasis (bis v1.3.1)

- `getList`/`getOne` unter `/clean/record/` liefern abgeschlossene Aufzeichnungen
  ohne Roboterbewegung. Die zuvor getestete Fork-Kamera zeichnet nur `posArray`.
- `getOne.map` ist ein Base64-kodierter LZ4-Block mit genau `width * height`
  Pixeln. Beobachtete Klassen: 127 = außerhalb, 255 = Boden, 0 = Wand/Rand.
  `x_min`, `y_min` und `resolution` orientieren die Fahrspur in Metern;
  `posArray` liegt in Millimetern. Keine Achse spiegeln.
- Die Kamera zeigte bis v1.3.1 die letzte abgeschlossene Reinigung.
  Die Bildabfrage ist fünf Minuten zwischengespeichert. Für beide vorhandenen
  Geräte wurden echte PNGs aus den Rohdaten erzeugt und geprüft.
- Lokaler Dekoder wurde gegen `lz4.block` für beide echten Karten bytegenau
  geprüft; zur Laufzeit wird keine zusätzliche LZ4-Abhängigkeit benötigt.

## Sperrzonen (Stand 2026-10-23)

- Die HA-Kamera renderte bis v1.3.1 nur die letzte Reinigungsaufzeichnung.
  `/clean/record/getOne` enthält bei beiden Geräten keine Sperrzonen; auch
  `getBackupMapList.areaSetting` war für alle vorhandenen Backups leer.
- Die reine Kartenabfrage `30000` mit `botslab360.rooms.LOAD_DATA` liefert per
  Push `20002` die aktuelle Karte. Bei der oberen Etage enthielt sie `mapId`,
  `AreaSettingId`, Karte und `area: []`, aber keine Sperrzonen-Geometrie.
  Der Status `20001` enthielt ebenfalls nur `AreaSettingId` und
  `isInForbidMode`, keine Koordinaten. Keine Sperrzonen erfinden oder aus
  `area: []` auf sichere Treppenabsicherung schließen.
- Die aktuelle Kartenantwort hatte Leerzeichen statt `+` in Base64; vor einer
  Decodierung der Live-Karte diese Form-Kodierung berücksichtigen. Deren
  Pixelklassen waren wie bei der Historie nur 0, 127 und 255.
- Für eine zuverlässige Anzeige zuerst die tatsächliche Zonenquelle und die
  Zuordnung zu `mapId`/Koordinaten ermitteln. Eine HA-Überlagerung allein
  konfiguriert keine Sperrzone im Roboter.

- Nach dem erneuten Setzen lieferte `30000`/`20002` auf der aktiven oberen Karte
  ein `area`-Element mit `active: "forbid"` und vier `vertexs` in Millimetern;
  `AreaSettingId` stieg, `mapId` blieb gleich. Die vom Nutzer aktivierte ältere
  untere Karte lieferte zwei solche Elemente. Ab v1.3.2 zeichnet die Kamera
  daher die **aktive** Karte mit roten Sperrflächen und die letzte Fahrspur nur
  bei exakt passenden Kartenmaßen und Ursprung. Bei fehlender aktiver Karte
  wird kein altes Zonenbild weitergeliefert. Rote Flächen wurden mit beiden
  echten Karten visuell geprüft; sie sind keine Sicherheitsgarantie.
- HA bricht Kamera-Bildabfragen nach 10 Sekunden ab. Ab v1.3.3 laufen die
  optionale historische Fahrspur und die aktuelle Kartenabfrage gleichzeitig;
  auf eine langsame Fahrspur wird höchstens eine Sekunde gewartet. Die Kamera
  meldet ihre PNG-Bilder mit `image/png`. Sperrzonen stammen weiterhin nur aus
  der aktiven Karte.
- Live mit beiden Geräten geprüft: unten zwei, oben eine `forbid`-Fläche; die
  jeweilige HA-Kameramethode lieferte in rund drei Sekunden PNG mit roten Pixeln.
  Auf dem Zielsystem lief v1.3.3. In `.storage/lovelace` ist `Pi` die erste Ansicht;
  beide Mini-Karten nutzen `aspect_ratio: 1:1` und `fit_mode: contain`.
- Eine Sperrzone in HA zu *zeichnen* schützt den Roboter nicht. Zum Anlegen muss
  die Zone für die aktuelle `mapId` an das Gerät geschrieben und durch erneutes
  Lesen der aktiven Karte bestätigt werden. Der Schreibbefehl für manuelle
  S6-Sperrzonen ist noch nicht verifiziert; `26000 setAutoForbidArea` aus der
  öffentlichen 360-Protokollliste bezeichnet eine automatische Zone, nicht
  die hier benötigte Rechteck-Geometrie. Keine Mutationsbefehle zum Probieren
  an den Roboter senden.
- `changeMap` (`21025`) lädt laut App-Protokoll einen Backup-Datensatz anhand
  `cleanId`, `downUrl`, `md5`, nicht allein anhand der `mapId`. Bei den hier
  abgefragten Backups war `areaSetting` leer. Automatisches Wiederherstellen
  könnte daher die Treppensperre verlieren; bei Kartenwechsel zunächst HA-Start
  blockieren und Sperrzonen auf der aktiven Karte prüfen. Das
  [S6-Handbuch](https://www.botslab360.com/uploads/soft/20230801/1-230P114535aA.pdf)
  bestätigt, dass eine neu erzeugte Karte bisherige Sperrzonen verliert.

## Geplante benannte Bereichsreinigung

- Gewünscht sind in HA selbst gezeichnete und benannte Rechtecke auf der Karte
  (z. B. Bad), die über eine Roboter-Detailansicht gezielt gestartet werden.
  Das sind keine automatisch erkannten Räume. Die Zone muss an die aktuelle
  Gerätekarte (`mapId`, Ursprung und Auflösung) gebunden sein; bei einer neu
  erzeugten Karte darf ein alter Bereich nicht startbar bleiben.
- `botslab360==0.7.1` kann erkannte Räume reinigen, bietet aber keine frei
  gezeichnete Zonenreinigung. Bei den aktuellen S6-Kartendaten war `area: []`
  und `smartArea` fehlte. Deshalb die Raum-API nicht als Zonen-API ausgeben.
- Statische Analyse der auf dem eigenen Android-Handy installierten 360Robot-App
  11.1.7 (`com.qihoo.smarthome`): `SweeperPresenter.startAreaSweep` verwendet
  für Geräte ohne `supportBlockClean` (bei beiden S6 nicht im Support-JSON)
  einen `30000`-Sammelbefehl mit zwei `cmds`:
  `21023` enthält `SweepAreaEnable{mapId, cleanId:[-2], extraAreas:[SweepArea]}`;
  `21005` enthält `SweepCmd{mode:"reAppointClean"}` für einen neuen Lauf.
  `mainCmds` enthält `"21005"`. Der App-Befehl wurde nur aus Code gelesen,
  nie an die Geräte gesendet. Vor einer produktiven Schaltfläche mit Mockdaten
  prüfen und nach neuer Karte bewusst mit dem Nutzer testen.
- `SweepArea.setRectF` schreibt vier Eckpunkte im Uhrzeigersinn als ganzzahlige
  Millimeterwerte (`vertexs`); der Builder setzt bei einer normalen Zone
  `active:"normal"`, außerdem `id` und `name` (`rect<id>` in der App).
  Die Frontend-Pixel müssen über `x_min`, `y_min`, `resolution` in dieselben
  Kartenkoordinaten umgerechnet werden wie die bisherige Fahrspur.
- Für die Oberfläche eignet sich eine Lovelace-Subview, zu der die Roboter-Kachel
  navigiert. Home Assistants eingebaute `picture-elements`-Karte kann gespeicherte
  Rechtecke zeigen; eine komfortable Zeichnen-/Speichern-Funktion braucht eigene
  lokale Frontend-Logik und einen Speicherweg in der Integration.

## Vorübergehende Startsperre für gefährdete Etagen

- Ab v1.3.1 sperrt die Config-Entry-Option `blocked_start_sns` (Liste von
  Geräte-Seriennummern) `vacuum.start` für ausgewählte Roboter. Die START-
  Fähigkeit wird bei diesen Entities ausgeblendet; `async_start` prüft
  zusätzlich vor jedem API-Aufruf und wirft einen HA-Fehler. Für andere
  Roboter bleiben Start und Status unverändert.
- Auf dem Zielsystem ist der Zeitplan für den oberen Roboter per
  `initial_state: false` abgeschaltet. Die Startsperre gilt nur für HA;
  App, Gerätetaste und herstellereigene Zeitpläne bleiben davon unabhängig.
  Vor einem erneuten Freigeben zuerst die aktuelle Karte, Treppensicherung
  und physischen Schutz prüfen.
