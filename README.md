# Fruit Picking Vision

Teaching a dual-arm service robot to **detect and pick plastic fruits and vegetables** with a YOLOv5 detector and a voice/LLM command interface.

This repository documents my own work during an internship: the data-collection protocol, the labeling rules, tooling fixes, and (soon) training experiments and results. The robot control software, teaching material and lab infrastructure belong to the host lab and are **not** included.

## Goal

> *"How many apples are there?"* → *"Give me the banana."* → *"Sort the rest."*

The robot hears a command, understands it, finds the right object with its camera, and picks it.

## Pipeline

```
 voice ──► speech-to-text ──► LLM (command as JSON) ──► robot task API
                                                              │
 head camera (RGB-D) ──► YOLOv5 detector ──► box + class ─────┤
                              ▲                               ▼
                       trained in this repo        depth → 3D point → camera-to-robot
                                                   calibration → grasp planning → pick
```

Only the **detector** is trained. Calibration is computed once, grasp planning is programmed, and the speech/LLM services are used as they are. See [docs/pipeline.md](docs/pipeline.md).

## Classes

| ID | Class | Note |
|---|---|---|
| 0 | `banana` | |
| 1 | `pepper` | |
| 2 | `potato` | |
| 3 | `apple` | |
| 4 | `battery` | intruder class: a non-food object to remove |

The order is fixed in [configs/classes.txt](configs/classes.txt) and must never change, because it defines the class IDs.

## Status

| Step | State |
|---|---|
| Capture protocol | ✅ [docs/data_collection.md](docs/data_collection.md) |
| Image capture (head camera, 1280×720) | 🟡 6 sessions, 295 images |
| Labeling rules | ✅ [docs/labeling_guide.md](docs/labeling_guide.md) |
| Seed labeling (S1 + S2, by hand) | 🟡 74 / 100 images |
| LabelImg on Python 3.10 | ✅ fixed, see [docs/labelimg_python310_fix.md](docs/labelimg_python310_fix.md) |
| Annotation assistant (pre-labeling S3–S6) | ⬜ |
| First detector `fruit01` + evaluation | ⬜ [experiments/](experiments/) |
| Deployment on the robot | ⬜ |
| Voice command spec (sort, pick, remove, count) | ✅ [docs/voice_commands.md](docs/voice_commands.md) |
| Intent test set (60 sentences, EN + ZH) | ✅ [tests/intent_test_set.csv](tests/intent_test_set.csv) |
| LLM prompt + validation for the new commands | ✅ [voice/](voice/) (offline self-test passes) |
| Intent accuracy | ✅ 31/31 on an unseen hold-out set, 0 unsafe; mini model as accurate as pro and ~2× faster ([run log](experiments/README.md)) |

## Repository layout

```
configs/      class list
docs/         pipeline, capture protocol, labeling guide, voice commands, tool fixes
experiments/  run log and results (one entry per training run)
tests/        intent test set for the voice commands
voice/        intent module (prompt, validation) and evaluation script
```

Images, labels and model weights are not stored in git (see `.gitignore`).

## Tools

- [YOLOv5](https://github.com/ultralytics/yolov5) (Ultralytics) for detection
- [LabelImg](https://github.com/HumanSignal/labelImg) for bounding-box labeling (Pascal VOC)
- Intel RealSense D435 camera

## Author

Mohamed Hedi Kammoun
