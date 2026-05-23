# 360 Vacuum Robot — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io)

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
| Battery level | ✅ |
| Status (cleaning / docked / paused / returning) | ✅ |
| Multiple robots (same account) | ✅ |
| Real-time status via TCP push | 🔜 planned |
| Room/zone cleaning | 🔜 planned |

---

## Prerequisites

- Home Assistant 2024.1 or newer
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

The integration authenticates using two values from your 360 account session: **QID** and **SID**. These are extracted from the running app via ADB.

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

### Step 3 — Extract QID and SID

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

You can ignore `pushkey` for now (reserved for future real-time status).

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
3. Enter your **QID** and **SID**
4. Click Submit — the integration will discover all robots on your account automatically

---

## Session Expiry

The SID session expires approximately every 12 hours. When this happens, Home Assistant will show a **Re-authenticate** notification for the integration. Simply extract a new SID via ADB (Step 3 above) and enter it in the prompt.

---

## Troubleshooting

### Integration not found after restart
Make sure the `custom_components/vacuum_360/` directory is in the correct location and contains all files. Check HA logs for errors.

### "Authentication failed"
Your SID has expired or is incorrect. Extract a fresh SID via ADB and re-enter it.

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
- Real-time status via TCP push socket

---

## License

MIT — see [LICENSE](LICENSE)
