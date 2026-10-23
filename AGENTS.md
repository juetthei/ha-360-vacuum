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
├── map_guard.py       Bekannte Sperrfläche auf aktiver Karte prüfen
├── zones.py           Bestätigte Rechtecke gegen Live-Karte prüfen und starten
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

## Überwachung der oberen Treppensperre (ab v1.3.5)

- Die Config-Entry-Option `map_guards` enthält für oben die bestätigte `map_id`
  und die vier Eckpunkte der Treppensperre. Der neue Sensor `Treppensperre`
  fragt die aktive Karte alle fünf Minuten schreibfrei ab und meldet `safe`,
  `zone_missing`, `wrong_map` oder `check_failed`. Eine größere rechteckige
  Sperrzone auf derselben Karte gilt ebenfalls als sicher, wenn sie den
  bisherigen Bereich vollständig umfasst. Bei neuer Karte nie automatisch
  eine beliebige rote Fläche als Treppensicherung akzeptieren.
- `Robot360Vacuum.async_start` lädt vor jedem **HA-Start** die aktuelle Karte
  erneut und verweigert den Start bei jedem anderen Zustand als `safe`, auch
  wenn der Sensor noch einen alten Zustand anzeigt. App, Gerätetaste und
  Hersteller-Zeitpläne werden dadurch nicht blockiert.
- Auf dem Zielsystem sind zwei Automationen in `automations.yaml` aktiv: Bei
  `zone_missing`, `wrong_map`, `check_failed` oder `unavailable` erstellen sie
  eine HA-Dauermeldung und senden an den Notify-Dienst der Handy-App; bei
  `safe` wird die Dauermeldung entfernt. Der frühere statische
  `blocked_start_sns`-Eintrag für oben ist leer. Keine Roboteraktion wurde zur
  Prüfung ausgelöst. Bei einer neu erzeugten Karte nach manueller Kontrolle
  des Treppenbereichs die `map_guards`-Referenz bewusst aktualisieren.
- Die Pi-Lovelace-Kachel hatte zusätzlich unabhängig von der Integration den
  Text `Start gesperrt` und nur `return_home` in `vacuum-commands`. Nach der
  Freigabe der überwachten HA-Starts wurden dort `Robot: oben` und
  `start_pause` + `return_home` wiederhergestellt. Bei UI-Sperren stets auch
  die Lovelace-Kartenkonfiguration prüfen.

## Geplante benannte Bereichsreinigung

- Während einer vom Nutzer gestarteten Schlafzimmer-Reinigung oben lieferte
  die aktive Karte neben der Treppensperre genau eine gezeichnete Fläche
  `active: "normal"`, `id: 2`, `name: "rect2"`. Deren vier Millimeter-Eckpunkte
  wurden als **Schlafzimmer oben** in der privaten HA-Datei
  `/config/.storage/vacuum_360_saved_zones` gespeichert, zusammen mit der
  aktiven `map_id` und Gerätezuordnung. Datei gehört nicht ins öffentliche
  Repo. Der Speicherstand allein löst keinen Auftrag aus. Bei neuer Karte
  die gespeicherte Fläche nicht ungeprüft verwenden.
- Der Nutzer bestätigte nach Abschluss: `rect2` war das Schlafzimmer. Im
  schreibfreien Nachlauf meldete der Roboter `charge`; dieselbe `map_id`,
  `rect2` und die Treppensperre waren weiter vorhanden (`safe`). Die private
  Zonendatei ist mit `confirmed_by_user` und `observed_after_run` markiert.
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
- Ab v1.4.0 lädt `vacuum_360.clean_zone` eine bestätigte Zone aus der privaten
  HA-Storage-Datei. Der Dienst prüft vor dem Start die aktuelle `mapId`, die
  Treppensperre und den Roboterstatus (`charge`, `fullcharge`, `idle`, `standby`).
  Dann sendet `Api360.clean_zone` den aus der App rekonstruierten Sammelbefehl.
  **Der echte Zonenstart ist weiterhin nicht am Gerät getestet.** Bei Fehlern
  keine Vollreinigung als Fallback auslösen. Mocktests prüfen Nutzdaten und
  Startverweigerung; ein schreibfreier Live-Durchlauf mit echtem Status und
  Karte endete vor dem durch Mock ersetzten Startbefehl erfolgreich. Bei einem
  ersten Nutzer-Test Treppe physisch schützen. Die bei der App-Bereichsreinigung
  beobachteten Modi `sweep` und `reAppointClean` werden als Reinigung angezeigt.
- Die Pi-Kachel oben navigiert zur Lovelace-Subview `robot-oben`. Darin sind
  Schlafzimmer und Flur als Knöpfe aktiv. Bad, Büro und Kinderzimmer bleiben
  nicht startbare Platzhalter; das Bad ist zwar gespeichert, sein Knopf aber
  noch inaktiv. Die aktuelle `normal`-Fläche wird auf der Kamerakarte blau
  gezeichnet, `forbid` bleibt rot. Für Büro und Kinderzimmer zuerst echte
  Rechtecke auf der aktiven Karte erfassen; keine Koordinaten erfinden.

- Stand 2026-10-23: Der Nutzer bestätigte „Bad oben“ anhand der zuletzt
  abgeschlossenen Fahrt. Alle 757 Fahrspurpunkte lagen im damals aktiven
  Rechteck, keiner in der Schlafzimmer-Zone. Die private HA-Storage-Datei
  enthält `bad_oben` zusätzlich zu `schlafzimmer_oben`.
- „Flur oben“ besteht aus zwei vom Nutzer bestätigten Rechtecken auf derselben
  aktiven Karte. Sie liegen als eine Zone `flur_oben` mit `areas`-Liste in
  der privaten HA-Storage-Datei. `observed_after_run` ist `false`, da
  die letzte abgeschlossene Fahrt noch das Bad zeigte. Die aktuelle Karte
  zeigt die beiden blauen Flächen, während die orange Fahrspur weiterhin
  die letzte abgeschlossene Reinigung zeigt.
- Ab v1.5.0 akzeptiert `clean_zone` weiter einzelne Rechtecke mit
  `vertices` sowie Gruppen mit `areas`. Alle Rechtecke einer Gruppe
  werden als `extraAreas` in einem einzigen `30000`-Befehl übergeben.
  Vorher werden alle vier Millimeter-Eckpunkte und eindeutige Teilflächen-IDs
  geprüft; die bestehende HA-Startsperre gilt ebenfalls. Die 18 Mocktests
  liefen im HA-Container erfolgreich. Auf dem Zielsystem war v1.5.0 installiert
  und der Flur-Knopf ruft `vacuum_360.clean_zone` mit `flur_oben` auf.
  Nach dem HA-Neustart: HTTP 200 und Treppensperren-Sensor `safe`.
  Ein echter Zonenstart bleibt ungetestet; kein Befehl wurde ausgelöst.

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
