# How the robot goes from a sentence to a grasp

A common misunderstanding is that the robot has one model that "learns to do tasks". It doesn't. Only one part is trained with data: the **detector**. Every other part is measured, calculated, programmed, or used as it is.

| # | Stage | Kind | What goes in → what comes out |
|---|---|---|---|
| 1 | Speech → text | used as is (cloud speech recognition) | 16 kHz mono audio → text |
| 2 | Text → command | used as is (LLM) + **a prompt I write** | "give me the banana" → `{"command": ..., "reply": ...}` |
| 3 | See | **trained** (YOLOv5) | RGB image → class + box in pixels |
| 4 | Pixel → 3D | measured (depth camera) | box center → distance from the camera |
| 5 | Camera → robot | calculated once (hand–eye calibration) | point in the camera frame → point in the robot base frame |
| 6 | Move and grasp | programmed (robot software) | target position → arm path, open hand, grasp, lift, place |

## What changes for a new set of objects

| I want | What I change | Stage |
|---|---|---|
| Recognize new objects | new labeled images → retrain the detector | 3 |
| The robot uses the new model | swap the weights file and the class names on the robot | 6 |
| A new task (e.g. bananas go to bin 2) | the class → place mapping in the task code | 6 |
| Voice commands with the new names | the LLM prompt and the allowed command list | 2 |
| Accurate grasps | redo calibration only if the camera moved | 5 |

## Why the training camera matters

The detector works best on images that look like its training images. The robot detects with its **head camera**, so all training and validation images come from that camera: same resolution, same viewpoint, same colors. Phone photos were considered and rejected: the objects look much bigger and sharper in them, and they would make the validation score look better than the robot's real performance.

## Safety design for voice commands

The LLM never controls the robot directly:

- it can only answer with a command from a fixed list (anything else → `NONE`, nothing is sent);
- the reply is checked strictly before use (exact keys, allowed values);
- motion commands need a human confirmation that expires after a short time;
- "stop" and "status" bypass the LLM entirely;
- an accepted request is not treated as a completed action.

The object-specific commands (sort, pick, remove, count a class) follow the same rules; see [voice_commands.md](voice_commands.md).

## The interface between detection and grasping

[detector/fruit_detector.py](../detector/fruit_detector.py) returns, for every frame, a list of `class_name`, `confidence` and `bbox` in original-image pixels. [detector/fruit_localizer.py](../detector/fruit_localizer.py) adds stages 4 and 5: median depth in the box (depth aligned to color) → 3D point in the camera frame (color intrinsics) → point in the robot World frame with the head-camera calibration matrix. The grasping side receives `xyz_world` per object and plans the motion.
