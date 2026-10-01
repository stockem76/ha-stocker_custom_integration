# Stocker Vision for Home Assistant

Local recognition of visitors and vehicles from Tapo cameras, announced on Alexa with a stated level of confidence ("I think Mark is at the front door").

Architecture and roadmap: [docs/DESIGN.md](docs/DESIGN.md).

**Current phase (P1):** builds on Frigate's local face recognition and number plate recognition. It turns Frigate's stream of recognition updates into one decision per visit, with confidence levels, cooldowns and unknown-person detection, then raises Home Assistant entities and events and announces them on Alexa.

## Prerequisites

1. **Mosquitto broker** add-on and the MQTT integration.
2. **Frigate** add-on (0.16+) with `face_recognition` and `lpr` enabled. See [docs/frigate.yml](docs/frigate.yml) for a template tuned for a 5th-gen Intel NUC.
   - Tapo D235: hardwired, jumper fitted, Always-On mode, plus a camera account set up in the Tapo app.
   - Tapo C500: a camera account set up in the Tapo app.
3. Train faces in Frigate's **Face Library** and name known plates under `lpr.known_plates`.
4. **Alexa Media Player** (HACS) for announcements.

## Installation

**HACS:** add this repository as a custom repository (category *Integration*), install it, then restart Home Assistant.

**Manual:** copy `custom_components/stocker_custom_integration` into `config/custom_components/` and restart.

Then go to **Settings → Devices & Services → Add Integration → Stocker Vision**. Tune the thresholds under **Configure**.

## What you get

| Item | Description |
| --- | --- |
| `sensor.stocker_vision_last_visitor` | Name or "Unknown". Attributes: confidence, level, camera, message |
| `sensor.stocker_vision_last_vehicle` | Vehicle name or plate |
| `binary_sensor.stocker_vision_<name>_seen` | Created automatically for each recognised person or vehicle. On for the presence window. |
| Event `stocker_vision_visitor` | `kind`, `name`, `confidence`, `level` (certain/likely/unknown), `camera`, `message` |
| Event `stocker_vision_vehicle` | The same, plus `plate` |

### Alexa announcements

Import the blueprint [blueprints/automation/stocker_vision/announce_on_alexa.yaml](blueprints/automation/stocker_vision/announce_on_alexa.yaml). Pick your Echo devices, the confidence levels to announce, the cameras, and quiet hours.

### Settings

| Option | Default | Meaning |
| --- | --- | --- |
| Certain at or above | 0.90 | Announced plainly |
| Likely at or above | 0.75 | Announced as "I think…". Lower scores are not announced. |
| Cooldown | 120 s | Don't repeat the same person, vehicle, or unknown-at-camera |
| Unknown delay | 6 s | How long to wait for a face before saying "someone I don't recognise" |
| Unknown cameras | all | Limit unknown-person announcements, e.g. `front_door` |
| Announce unknown plates | off | Read out unrecognised registrations |
| Presence window | 10 min | How long the `*_seen` sensors stay on |

## Privacy

Face and gait templates are biometric data. Only enrol people who have agreed. Keep Frigate retention short, and use zones so the street isn't analysed. See DESIGN.md §5.

## Development

Home Assistant itself doesn't install on Windows. Locally, `pytest` runs the standalone recognition tests and skips the rest. CI on Linux runs everything, plus hassfest and HACS validation.

```bash
pip install pytest ruff
pytest
ruff check .
```
