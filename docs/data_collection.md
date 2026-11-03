# Data collection protocol

All images are taken with the robot's **head camera** (Intel RealSense D435, color stream only, 1280×720, PNG). The camera is fixed, so variety comes from the scene: object position, rotation, grouping, background and lighting.

## Principles

- **Same camera as deployment.** No phone photos.
- **Change something between every photo** (position, rotation, which objects, grouping). Two near-identical photos are worth one.
- **Cover the whole reachable table**, not only the center: near, far, corners.
- **No hands** in the frame; wait for the scene to be still.
- **Balance the classes**: each class should appear about equally often over all sessions.
- **One capture run = one session.** Sessions are the unit of the train/validation split.

## Sessions

| Session | Content | Goal |
|---|---|---|
| S1 | one object per photo, each class at many positions and rotations | single-object views |
| S2 | 2–3 objects, spread out | simple multi-object scenes |
| S3 | all classes + the intruder, some touching | realistic mixed scenes |
| S4 | mixed scenes in darker light | low-light robustness |
| S5 | mixed scenes (originally planned as bright light) | extra variety |
| S6 | hard cases: clutter, distractors, partial occlusion, other backgrounds | robustness |
| S7 | empty table / only non-target objects | background examples |

There was no light source strong enough for a real over-exposure session. Brightness robustness therefore relies partly on YOLOv5's HSV augmentation; this is a known limitation.

### Hard cases (S6)

- **Clutter:** many objects close together, random orientations.
- **Distractors:** everyday objects that are *not* targets (cup, ball, pen, a yellow object). They are not labeled, so the model learns "round and colored" is not enough.
- **Occlusion:** objects behind or on top of each other, partly covered, cut by the image edge.
- **Backgrounds:** white sheet, dark cloth, patterned cloth. Every class appears on every background, so no class gets tied to one color.

Each object must still be recognizable by a person; otherwise it is noise, not a hard case.

## Train / validation split

Photos from the same session look alike. A random split would put near-duplicates in both sets and inflate the score. The split is therefore **by whole session**: the hardest, most realistic sessions (e.g. S3 + S6) form the validation set, and the rest is training data.

## File naming

The capture tool numbers files from 1 in every session, so the same file name appears in each session folder. Before labeling, every image is copied into one flat folder with its session as a prefix:

```
S1_head_000001.png, S1_head_000002.png, ..., S2_head_000001.png, ...
```

Raw session folders are kept untouched as the original copy.

## Progress

| Session | Images |
|---|---|
| S1 | 65 |
| S2 | 35 |
| S3 | 51 |
| S4 | 51 |
| S5 | 81 |
| S6 | 12 |
| **Total** | **295** |
