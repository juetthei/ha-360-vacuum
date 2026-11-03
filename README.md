# 360 Vacuum Robot — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-blue.svg)](https://www.home-assistant.io)

Home Assistant custom component for **Qihoo 360 vacuum robots** (360 AI CleanRobot S6 and similar models). Controls your robot directly through the 360 Smart Home Cloud API — no local API, no Google Assistant workaround.

> **Android only.** The credential extraction process requires ADB and an Android phone running the 360 app. There is currently no known method to extract the required credentials on iOS. Pull requests welcome.

---

## Supported Devices

Tested with:
- **360 AI CleanRobot S6** (model 360TY...)

Likely compatible (same cloud API, untested):
- 360 S7, S9, S10 and other 360/Botslab models using the `q.smart.360.cn` cloud

---

## Features

| Feature | Status |
|---------|--------|
| Start cleaning | ✅ |
| Pause | ✅ |
| Return to base / Stop | ✅ |
| Battery level | ✅ (separate sensor entity) |
| Volume (0–100 % in 10 % steps) | ✅ (`number` entity, `21024 setVolume`, verified on S6) |
| Locate (robot plays a sound) | ✅ (`21020`, verified on S6) |
| Suction power (Leise / Standard / Power) | ✅ (`vacuum.set_fan_speed`, `21022`, verified on S6) |
| Current map and no-go zones | ✅ (camera entity; last cleaning path shown when map coordinates match) |
| Guard a known no-go zone | ✅ (5-minute map check, sensor state and live check before HA start when configured) |
| Create no-go zones | ➖ not supported — create them in the 360 app; HA displays and guards them |
| Status (cleaning / docked / paused / returning) | ✅ |
| Multiple robots (same account) | ✅ |
| Status via encrypted push channel | ✅ (polled every 30 s) |
| Saved rectangular zone cleaning | ✅ verified on S6 with a single rectangle; requires a map guard |

### Entities

Each robot gets one device with vacuum, battery, and map entities:

| Entity | Description |
|--------|-------------|
| `vacuum.<robot_name>` | Status and controls (start / pause / return to base / stop / fan speed / locate) |
| `sensor.<robot_name>_battery` | Battery level in % |
| `camera.<robot_name>_karte` | Active floor plan with no-go zones in red; last route when coordinates match |
| `sensor.<robot_name>_treppensperre` | `safe`, `zone_missing`, `wrong_map` or `check_failed` when a map guard is configured |

Saved cleaning areas (e.g. "Kitchen", "Bathroom") are started with
`vacuum_360.clean_zone`; see [Saved Cleaning Areas](#saved-cleaning-areas).

> **Upgrading from 1.0.x on Home Assistant 2026.9 or newer:** battery used to be
> the `battery_level` attribute of the vacuum entity. Home Assistant 2026.9
> removed battery support from vacuum entities entirely, so it is now its own
> sensor entity. Dashboards or automations reading the old attribute must be
> pointed at `sensor.<robot_name>_battery` instead. The sensor reads the live
> battery value from the encrypted 360 push channel and needs the `pushkey`
> from the same app session as QID and SID.

---

## Prerequisites

- Home Assistant 2025.1 or newer
- An Android phone with the **360 Smart** app installed and logged in
- ADB (Android Debug Bridge) — installed on your PC or server
- USB cable (or wireless ADB) to connect the phone

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations**
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/juetthei/ha-360-vacuum` with category **Integration**
4. Search for **360 Vacuum Robot** and install
5. Restart Home Assistant

### Manual

1. Download or clone this repository
2. Copy the `custom_components/vacuum_360` folder into your HA config directory:
   ```
   config/custom_components/vacuum_360/
   ```
3. Restart Home Assistant

---

## Getting Your Credentials (Android + ADB)

The integration uses **QID**, **SID**, and **push key** from the same 360 app session. The push key decrypts battery and other status messages. Extract all three from the running app via ADB.

### Step 1 — Enable USB Debugging on your phone

1. Go to **Settings → About phone**
2. Tap **Build number** 7 times to unlock Developer Options
3. Go to **Settings → Developer Options**
4. Enable **USB Debugging**

### Step 2 — Connect and verify ADB

Connect your phone via USB, then on your computer:

```bash
adb devices
```

You should see your device listed (not "unauthorized"). If it says "unauthorized", check your phone for a popup asking to allow USB debugging — tap **Allow**.

### Step 3 — Extract QID, SID, and push key

Open the 360 app on your phone and make sure you are logged in. Then run:

```bash
adb logcat | grep MyPushMessageListener
```

Wait a few seconds. You will see a line like this:

```
D MyPushMessageListener.java: push_debug pushkey:a1b2c3d4e5f6789012345678abcdef01 qid:1234567890 sid:fedcba9876543210fedcba9876543210
```

Your values are:
- **QID** — the 10-digit number after `qid:` (e.g. `1234567890`)
- **SID** — the 32-character hex string after `sid:` (e.g. `fedcba9876543210fedcba9876543210`)
- **Push key** — the 32-character value after `pushkey:`

Keep all three values private; the push key is required for battery status.

> **Tip:** If nothing appears, close and reopen the 360 app, or log out and back in.

### Step 4 — Wireless ADB (optional, no USB cable)

If your phone and PC are on the same network:

```bash
# On the phone: Settings → Developer Options → Wireless debugging → enable
# Note the IP and port shown on screen, then on your PC:
adb connect 192.168.x.x:PORT
adb logcat | grep MyPushMessageListener
```

---

## Configuration in Home Assistant

1. Go to **Settings → Integrations → Add Integration**
2. Search for **360 Vacuum Robot**
3. Enter your **QID**, **SID**, and **push key**
4. Click Submit — the integration will discover all robots on your account automatically

---

## Saved Cleaning Areas

The S6 has no room segmentation that Home Assistant could use, but the app can
clean freely drawn rectangles. This integration replays such rectangles on
demand, so a dashboard button can clean one room.

### How it works

- An **area** is one rectangle or a group of rectangles (e.g. an L-shaped
  hallway) on one specific robot map. Coordinates are millimetres in the
  robot's map frame, exactly as the robot reports them.
- `vacuum_360.clean_zone` sends all rectangles of an area in **one** job
  (`21023` area list + `21005 reAppointClean` in a `30000` batch, as the app
  does). The cleaning mode recorded by the app (`normal` or `depth`) is kept.
- Before sending, the integration reloads the active map and refuses to start
  if the map ID changed, a guarded no-go zone is missing, the robot is not
  docked/idle, or a rectangle is malformed. It never falls back to a full
  cleaning.
- A new map (re-mapping) gets a new map ID; saved areas of the old map are then
  refused instead of being cleaned in the wrong place.
- Rectangles inside a no-go zone are not cleaned — the no-go zone wins.

### Recording an area

There is no drawing UI in Home Assistant yet. Areas are taken from the app:

1. In the 360 app, open area cleaning, draw the rectangle(s) for one room and
   **start** the cleaning. Drawn but unsent rectangles stay on the phone.
2. A few seconds after the start, the active map reports the rectangles. The
   camera entity draws them blue. Read their coordinates, e.g. from the
   Home Assistant container:

   ```python
   map_data = await api.get_current_map(serial)   # Api360 from this integration
   print(map_data["mapId"], [(a["id"], a["name"], a["active"], a["vertexs"])
                             for a in map_data["area"]])
   ```

3. Add the area to `<config>/.storage/vacuum_360_saved_zones` (create the file
   if needed). Areas are read on every service call; no restart is required.

   ```json
   {
     "version": 1,
     "minor_version": 1,
     "key": "vacuum_360_saved_zones",
     "data": {
       "zones": [
         {
           "id": "kitchen",
           "name": "Kitchen",
           "sn": "360TY0000000000",
           "map_id": 1234567890,
           "vertices": [[-1000, -3000], [-4000, -3000], [-4000, -500], [-1000, -500]],
           "active": "normal",
           "source_area_id": 2,
           "source_area_name": "rect2",
           "confirmed_by_user": true
         },
         {
           "id": "hallway",
           "name": "Hallway",
           "sn": "360TY0000000000",
           "map_id": 1234567890,
           "areas": [
             {"vertices": [[0, -4700], [-3900, -4700], [-3900, -3300], [0, -3300]],
              "active": "depth", "source_area_id": 3, "source_area_name": "rect3"},
             {"vertices": [[-400, -8300], [-1800, -8300], [-1800, -4700], [-400, -4700]],
              "active": "depth", "source_area_id": 4, "source_area_name": "rect4"}
           ],
           "confirmed_by_user": true
         }
       ]
     }
   }
   ```

   Only set `confirmed_by_user` after checking that the robot actually cleaned
   that room. `source_area_id` values must be unique within one area.

### Map guard (required)

`clean_zone` and `vacuum.start` only run for robots with a **map guard**: the
expected map ID plus the no-go zones that must still exist (e.g. the stair
zone). It is stored in the config entry options (`map_guards`, keyed by serial
number; no UI yet, edit while Home Assistant is stopped):

```json
"map_guards": {
  "360TY0000000000": {
    "name": "Sperrzonen",
    "map_id": 1234567890,
    "areas": [
      [[-5500, -8300], [-7600, -8300], [-7600, -5700], [-5500, -5700]],
      [[-5200, -5700], [-7600, -5700], [-7600, -4800], [-5200, -4800]]
    ]
  }
}
```

A single zone can also be given as `"vertices": [...]`. Each listed zone must be
present as a forbidden rectangle (a larger one covering it also counts). The
guard adds a sensor named after `name` (default `Treppensperre`) that checks
the map every five minutes. The guard only covers starts from Home Assistant;
the app, the robot's button and app schedules are not checked.

### Dashboard button

```yaml
type: button
name: Kitchen
icon: mdi:stove
tap_action:
  action: perform-action
  perform_action: vacuum_360.clean_zone
  data:
    zone_id: kitchen
  confirmation:
    text: Clean the kitchen now?
```

---

## Session Expiry

The SID session expires approximately every 12 hours. When this happens, Home Assistant will show a **Re-authenticate** notification for the integration. Extract a new SID and push key from the same ADB log entry (Step 3 above) and enter both in the prompt.

---

## Troubleshooting

### Integration not found after restart
Make sure the `custom_components/vacuum_360/` directory is in the correct location and contains all files. Check HA logs for errors.

### "Authentication failed"
Your SID has expired or is incorrect. Extract a fresh SID and push key from the same ADB log entry and re-enter both.

### Status always shows "unavailable" or "idle"
Enable debug logging to see the raw API response:

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.vacuum_360: debug
```

Restart HA and check **Settings → System → Logs** for `GetList response`. Open a GitHub issue and include that log line — different firmware versions may use different field names.

### Robot not found / wrong robot count
The integration uses your account's device list. Make sure the robot is registered in the 360 app under the same account as your QID/SID.

---

## Dashboard

A ready-to-use dashboard configuration is included in [`dashboard_example.yaml`](dashboard_example.yaml).

It uses only **built-in HA cards** — no HACS frontend components required.

### Single robot card

```yaml
type: vertical-stack
cards:
  - type: entity
    entity: vacuum.your_robot_name
    name: 360 Robot
    icon: mdi:robot-vacuum
  - type: horizontal-stack
    cards:
      - type: button
        name: Start
        icon: mdi:play
        tap_action:
          action: call-service
          service: vacuum.start
          target:
            entity_id: vacuum.your_robot_name
      - type: button
        name: Pause
        icon: mdi:pause
        tap_action:
          action: call-service
          service: vacuum.pause
          target:
            entity_id: vacuum.your_robot_name
      - type: button
        name: Return
        icon: mdi:home-map-marker
        tap_action:
          action: call-service
          service: vacuum.return_to_base
          target:
            entity_id: vacuum.your_robot_name
      - type: button
        name: Stop
        icon: mdi:stop
        tap_action:
          action: call-service
          service: vacuum.stop
          target:
            entity_id: vacuum.your_robot_name
```

Replace `vacuum.your_robot_name` with your actual entity ID (find it under **Settings → Entities**, search for "360" or "vacuum"). The full two-robot panel layout is in `dashboard_example.yaml`.

---

## Technical Background

360 vacuum robots have **no local API** — no open TCP ports, no web interface, no Xiaomi MiIO protocol. All communication goes through the 360 Smart Home Cloud (`q.smart.360.cn`).

This integration was reverse-engineered from:
- Network traffic analysis of the 360 Smart app
- The [stonegray.ca blog post](https://stonegray.ca/blog/360vac/) (December 2023)
- The [ioBroker botslab360 adapter](https://github.com/TA2k/ioBroker.botslab360)
- The [HA community thread](https://community.home-assistant.io/t/360-s6-vacuum-robot/124990) (2019–2025)

Authentication uses cookies (`qid` + `sid`) obtained from the running app session. Commands are sent as `POST` requests to `/clean/cmd/send` with URL-encoded payloads.

---

## Contributing

Pull requests welcome — especially:
- Confirmation of working models (please open an issue with your model name)
- iOS credential extraction method

---

## License

MIT — see [LICENSE](LICENSE)
