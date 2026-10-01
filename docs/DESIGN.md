# Stocker Vision: Design

Status: **draft for review** · 2026-10-01

## 1. Goal

Identify who or what is approaching the house from local camera feeds, and announce it on Alexa with a stated level of confidence.

| Capability | Signal | Output |
| --- | --- | --- |
| Known person | Face (primary), gait (supporting) | "Mark is at the door" |
| Visitor type | Clothing and carried objects | "A delivery driver with a parcel", "A Royal Mail postman" |
| Vehicle | Number plate, type and colour | "Sarah's car has pulled onto the drive" |
| Learning | Unknown faces, gaits and plates are clustered | You assign each cluster to a person, a type or a vehicle |

Everything runs locally on the Intel NUC under HAOS. Nothing goes to the cloud except the final Alexa announcement.

## 2. Key constraint: where the models run

A custom integration runs **inside Home Assistant Core's Python process**. Running face, pose and gait models there would block the event loop, and HAOS doesn't let you install native ML dependencies there. The heavy work therefore runs in **containers (add-ons)**, and this integration is the glue on the HA side.

```
 Tapo D235 / C500 ──RTSP──► Frigate add-on ──MQTT events + snapshots/clips──► Stocker Vision add-on
                           (go2rtc, OpenVINO on                                 (pose → gait, role classifier,
                            the NUC iGPU: person/car                             clustering, identity store,
                            detection, face rec, LPR)                            score fusion, labelling UI)
                                                                                    │ REST + MQTT
                                                                                    ▼
                                                                    stocker_custom_integration (this repo)
                                                                     entities, events, services
                                                                                    │
                                                                                    ▼
                                                              Automation → Alexa Media Player → Echo announce
```

### 2.1 Frigate (existing add-on, reused rather than rebuilt)
- Ingests every camera through go2rtc. Uses OpenVINO on the NUC's Intel iGPU (6th gen or newer).
- Detects people, cars and other objects. Frigate 0.16+ also does **face recognition** and **number plate recognition**, publishes the results over MQTT, and has a face-library UI.
- Optional Frigate+ models add courier labels (Amazon, UPS, DHL, etc.) and a `package` label. Coverage of Royal Mail still needs checking.

### 2.2 Stocker Vision add-on (new, lives in this repo)
Triggered by Frigate `person` and `car` events, so the expensive models run only when something is actually there.

| Module | Approach (local, OpenVINO/ONNX) |
| --- | --- |
| Pose | YOLO11-pose or RTMPose → COCO-17 keypoint sequence per tracked person (the "wireframe stick" figure) |
| Gait | Skeleton-based gait embedding (GaitGraph2-style GCN) plus handcrafted features (cadence, stride and height ratios, limb proportions) |
| Face quality | OFIQ (BSI's open-source ISO/IEC 29794-5 implementation) decides which frames are good enough to store as templates or to match against |
| Role / type | Zero-shot CLIP/SigLIP on the person crop ("hi-vis vest", "Royal Mail uniform", "holding a parcel", "police uniform", etc.), combined with Frigate+ courier labels. A small local VLM through Ollama is optional as a slow fallback. |
| Vehicle | Plate from Frigate LPR, plus colour and body type from CLIP on the car crop |
| Clustering | HDBSCAN over the face and gait embeddings of unidentified tracks → "unassigned clusters" |
| Fusion | Score-level fusion of face, gait, plate and context (time of day, which camera) into one identity plus a confidence |
| Store | SQLite: persons, roles, vehicles, templates, sightings, clusters |
| UI | HA ingress web UI to review sightings and assign clusters to a person, role or vehicle |

### 2.3 This integration
- Config flow: discovers the add-on and connects to it.
- Entities: `sensor.<camera>_last_visitor` (name, role, confidence, evidence), `sensor.last_vehicle`, a `binary_sensor` per known person ("seen in the last N minutes"), and an `image` entity for the latest snapshot.
- Events: `stocker_vision_visitor`, `stocker_vision_vehicle`.
- Services: `create_person`, `assign_cluster`, `merge_persons`, `forget_person` (deletes all templates).
- Blueprint: an announce automation with confidence-aware wording ("I think it's Mark", "That's Mark", "Someone I don't recognise").

### 2.4 Hardware: NUC5i5RYK

i5-5250U (2 cores, 4 threads, AVX2) and HD Graphics 6000 (Broadwell). Consequences:
- **No iGPU inference.** OpenVINO's GPU plugin needs a 6th-gen chip or newer. Frigate detection, face and LPR all run on OpenVINO **CPU**, with Frigate's `small` face/LPR models.
- Video decode still uses VA-API (`i965` driver). Detect on substreams at 5 fps. The doorbell detects on the main stream scaled to 1280×960 so faces have enough pixels.
- **No local VLM.** The Ollama fallback in 2.2 is dropped. Role and vehicle classification use CLIP ViT-B/32-class models (about 150 ms per crop on this CPU), run on a few best frames per event only.
- Pose estimation uses YOLO11n-pose or RTMPose-t only (about 50–100 ms per frame on the CPU), run only on frames from person tracks on the gait cameras.
- **Recommended upgrade:** a Google Coral USB for Frigate detection. It frees most of the CPU for the Stocker Vision add-on.
- RAM: 8 GB minimum, 16 GB preferred.

Template config: [frigate.yml](frigate.yml).

## 3. Standards alignment

| Area | Standard | How it's used |
| --- | --- | --- |
| Face image capture and metadata | ISO/IEC 39794-5 (successor to 19794-5) | Store the template source image with pose, eye-distance and quality metadata in a 39794-5-shaped record |
| Face image quality | ISO/IEC 29794-5 (via OFIQ) | Gate both enrolment and matching |
| Matching performance | ISO/IEC 19795-1 | Log comparisons, then report FMR/FNMR and DET curves to set thresholds |
| Spoofing (photo held up) | ISO/IEC 30107-3 | Later phase. A low-risk use case, so a basic liveness check only. |
| Gait | No ISO interchange format exists | Store COCO-17 keypoint sequences. Evaluate like the CASIA-B and OU-MVLP benchmarks. |

## 4. Realistic expectations

- **D235 streams RTSP only when hardwired, with the jumper fitted and Always-On mode enabled.** On battery it can't feed Frigate. C500s need a "camera account" set up in the Tapo app for RTSP.
- **Face recognition** is reliable at the doorbell when the person is close and facing the camera. Accuracy drops with hoods, masks, glare or night IR.
- **Gait** from a doorbell, where the subject walks head-on toward a fisheye lens for only a few steps, is weak. Side-on views from the C500s on the drive or path work much better. Gait is used as a **supporting signal** for a small, closed set of household members and regular visitors, not as the only basis for identifying someone.
- **Role detection** works on visible cues (uniform, hi-vis, parcel, branded van). It will sometimes be wrong, so announcements are worded as probabilities.

## 5. Privacy and legal (UK GDPR)

Face and gait templates are special-category biometric data. If any camera covers the street or a shared footpath (doorbells usually do), the domestic exemption may not apply, and the ICO's guidance on domestic CCTV applies instead. The design therefore defaults to:
- Templates are stored only for people explicitly enrolled (household members and consenting regular visitors).
- Unknown clusters and sightings auto-expire (default 30 days). Unassigned plates expire too.
- Role labels ("postman") are not linked to a biometric identity unless you assign them to one.
- Everything stays local. `forget_person` erases all data about a person.
- Signage if the cameras cover public areas.

## 6. Delivery phases

| Phase | Scope | Value |
| --- | --- | --- |
| P0 | Install Frigate + OpenVINO, cameras via go2rtc, MQTT, Alexa Media Player | Infrastructure |
| P1 | Integration MVP: map Frigate face and plate results to persons and vehicles, entities, Alexa announcements | Named announcements for faces and cars |
| P2 | Add-on: role classifier, clustering of unknowns, labelling UI | "Delivery driver", building up the person library |
| P3 | Add-on: pose → gait templates, fusion with face | Gait-assisted ID |
| P4 | ISO/IEC 19795 evaluation report, threshold tuning, basic liveness | Measured accuracy |

## 7. Repo layout (target)

```
custom_components/stocker_custom_integration/   HA integration (HACS)
stocker_vision/                                  HA add-on (Dockerfile, config.yaml, app/)
repository.yaml                                  makes the repo installable as an add-on repository
blueprints/automation/stocker_vision/            Alexa announce blueprint
docs/
```
