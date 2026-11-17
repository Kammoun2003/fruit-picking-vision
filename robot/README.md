# Fruit robot server

The earlier battery demo's robot server grasps with taught poses per object type and its own detector, so it cannot pick a fruit at a measured position. `fruit_server.py` is a separate server for this project with **the same `/action` methods and reply formats**, so [voice/robot_bridge.py](../voice/robot_bridge.py) and the voice demo work unchanged. The battery demo is not modified.

```
voice demo ─► robot_bridge ─► POST :5000/action ─► fruit_server.py ─────────────► motion module
                                                    WHAT: which object, where,      HOW: arm and hand
                                                    work area, modes, stop          (fruit_motion.py)
                                                    detection: fruit_localizer
```

## Split of responsibilities

| Server (this folder) | Motion module (`fruit_motion.py`, robot side) |
|---|---|
| detection with the fruit localizer (class + World XYZ) | approach, grasp and lift heights |
| choice of the most confident object of the requested class | hand orientation for a top-down grasp |
| work-area check before any motion | SDK calls (Cartesian moves for the grasp, recorded joint positions for places) |
| work modes, automatic sorting, stop between objects | the recorded positions of the six places and home |
| the `/action` replies | checking every SDK result |

The motion module provides three functions that block until the motion has finished:

```python
pick_at(x, y, z) -> bool   # World frame, metres; z = top surface of the object (as from fruit_localizer)
place_at(name)   -> bool   # box_banana, box_pepper, box_potato, box_apple, waste_bin, hand_over
home()           -> bool
```

Only `True` counts as success; `False`, any other value or an exception is reported as a failed motion and the task stops.

## Methods

| Method | What the server does |
|---|---|
| `detect_objects`, `check_object_exist`, `check_count`, `get_target_position` | a fresh camera frame through the fruit localizer |
| `grasp_object(name)` | the most confident detection of `name`; if inside the work area: `pick_at(x, y, z)` |
| `move_object_to(name, to)` | `place_at(to)` if `to` is a known place and the object is held |
| `set_work_mode`, `query_work_mode` | manual / auto |
| `start_work` | automatic mode: everything into its place, batteries first, until nothing is left or an object cannot be grasped |
| `suspend_work` | stops automatic mode before the next object |
| `return_to_home` | `home()` |

`grasp_object` answers `[true, 0]` or `[false, code]`: 1 object not detected, 2 automatic mode, 3 outside the work area, 4 already holding an object, 5 motion failed.

## Configuration (`fruit_server_config.json`)

| Key | Meaning |
|---|---|
| `workspace` | allowed World X/Y/Z range for a grasp; anything outside never reaches the motion module |
| `places` | the place names `move_object_to` accepts (same as [voice/robot_places.json](../voice/robot_places.json)) |
| `class_places` | which place each class goes to in automatic mode |

The work area comes from the first measurements on the table and has to be confirmed with the arm.

## Running

Dry-run (default), nothing moves; the planned steps are printed:

```bash
python fruit_server.py --calibration <calibration_result.json> --serial <head camera serial>
```

A grasped object is hidden from later detections in dry-run, so SORT and automatic mode finish as they would for real. This is the first test on the robot: real camera, real detections, real World coordinates, voice commands through the bridge, no motion.

With the robot-side motion module:

```bash
python fruit_server.py --calibration <calibration_result.json> --serial <serial> --motion-module <path>/fruit_motion.py
```

The module's folder is added to the import path, so its own helpers (position manager, connection adapter) are found. Use it only after the reference-point check of the World coordinates, the measured grasp orientation and heights, and a dry-run of the same command. The software stop finishes the current motion; the hardware emergency stop stays at hand.

## Reference-point check (`refpoint_check.py`)

Before the arm grasps at camera coordinates, they are compared with the arm itself:

```bash
python refpoint_check.py --calibration <calibration_result.json> --serial <serial> --out refpoints.csv [--arm-units mm]
```

At each point (centre and the corners of the work area): put one fruit on the table, press Enter (the camera measures it), move the arm tip slowly to just above the fruit's centre, type the tip position shown by the controller. Every point is saved at once. `r` prints the table, `q` quits; `--report refpoints.csv` recomputes it later.

The table lists dX, dY per point (camera − arm), the common offset, and what is left after removing it, with a diagnosis:

| Diagnosis | Meaning |
|---|---|
| GOOD | every point within 10 mm in X/Y |
| CONSTANT OFFSET | almost the same error everywhere: a tool or frame offset, corrected with one constant shift |
| VARYING ERROR | the error changes across the table: check the work frame and the calibration first |

Z is listed but not judged: the camera measures the top surface, and the tip stays above it.

## Tests

```bash
python robot/test_fruit_server.py
python robot/test_refpoint_check.py
```

`test_refpoint_check.py`: 5 tests with synthetic arm positions around the measured table positions (small error, constant offset, an 8° rotation, Z ignored, report from a saved file).

15 tests with a fake camera (fruit positions measured on the real table). Through the voice bridge over HTTP: the planned grasp steps for PICK, SORT until none is left, REMOVE to the waste bin, COUNT and STATUS, a grasp outside the work area, a missing object, an unknown place, automatic mode (battery first, stops at an unreachable object), a grasp refused in automatic mode, an unknown method. With motion module files: World coordinates and place names reach the module (and its helper imports work), a draft returning `False`, an exception or a non-bool result count as failed motions, a module without the three functions is rejected, and a grasp outside the work area never reaches the module.
