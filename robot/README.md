# Fruit robot server

The earlier battery demo's robot server grasps with taught poses per object type and its own detector, so it cannot pick a fruit at a measured position. `fruit_server.py` is a separate server for this project with **the same `/action` methods and reply formats**, so [voice/robot_bridge.py](../voice/robot_bridge.py) and the voice demo work unchanged. The battery demo is not modified.

```
voice demo ─► robot_bridge ─► POST :5000/action ─► fruit_server.py
                                                    ├─ detection: fruit_localizer (class + World XYZ, head camera)
                                                    └─ motion: dry-run (default) or the real arm
```

## Methods

| Method | What the server does |
|---|---|
| `detect_objects`, `check_object_exist`, `check_count`, `get_target_position` | a fresh camera frame through the fruit localizer |
| `grasp_object(name)` | the most confident detection of `name`: move 10 cm above it → open the hand → straight down to 2 cm below its top surface → close → straight up 10 cm |
| `move_object_to(name, to)` | move to the taught pose of place `to` and open the hand |
| `set_work_mode`, `query_work_mode` | manual / auto |
| `start_work` | automatic mode: everything into its place, batteries first, until nothing is left or an object cannot be grasped |
| `suspend_work` | stops automatic mode before the next object |
| `return_to_home` | arm to its idle position |

`grasp_object` answers `[true, 0]` or `[false, code]`: 1 object not detected, 2 automatic mode, 3 outside the work area, 4 already holding an object, 5 motion failed, 6 grasp orientation not taught.

## Configuration (`fruit_server_config.json`)

| Key | Meaning |
|---|---|
| `workspace` | allowed World X/Y/Z range for a grasp; anything outside is refused |
| `approach_height_m`, `grasp_offset_m`, `lift_height_m` | heights relative to the fruit's top surface |
| `grasp_orientation` | `[rx, ry, rz]` of the hand for a top-down grasp, taught on the robot (`null` = not yet) |
| `places` | taught pose `[x, y, z, rx, ry, rz]` of each place; names match [voice/robot_places.json](../voice/robot_places.json) |
| `class_places` | which place each class goes to in automatic mode |

The work area comes from the first measurements on the table. The grasp orientation and the six place poses still have to be taught with the arm.

## Dry-run (default): nothing moves

```bash
python fruit_server.py --calibration <calibration_result.json> --serial <head camera serial>
```

Every planned pose is printed (`movej`, `movel`, `hand`) instead of being executed. A grasped object is hidden from later detections, so SORT and automatic mode finish as they would for real. This is the first test on the robot: real camera, real detections, real World coordinates, voice commands through the bridge, and no motion.

## Real motion

`--real` uses the lab's arm and hand classes (`Movej` / `Movel` to a pose, the hand's prepare and grasp postures). Connecting them (`make_real_motion`) is done on the robot together with the robot team, and only after:

1. the reference-point check of the World coordinates with the arm,
2. teaching `grasp_orientation` and the six place poses,
3. a dry-run of the same command whose printed poses have been checked.

The software stop finishes the current motion; the hardware emergency stop stays at hand.

## Tests

```bash
python robot/test_fruit_server.py
```

11 tests: the voice bridge against this server over HTTP with a fake camera (fruit positions measured on the real table): the planned grasp poses for PICK, SORT until none is left, REMOVE to the waste bin, COUNT and STATUS, a refused grasp outside the work area, a missing object, automatic mode (battery first, stops at an unreachable object), grasp refused in automatic mode, an unknown method; and the real motion layer with a fake arm: refused until the grasp orientation and places are taught, the exact call order, and a failed motion.
