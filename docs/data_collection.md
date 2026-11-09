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

Captured sessions, described from their final labels:

| Session | Images | Content | Boxes |
|---|---|---|---|
| S1 | 65 | one object per photo, food classes only | 65 |
| S2 | 35 | three objects per photo (apple, pepper, potato) | 105 |
| S3 | 51 | full mixed scenes: all five classes, about 9 objects per photo, touching and overlapping | 458 |
| S4 | 51 | full mixed scenes, as S3 | 462 |
| S5 | 81 | full mixed scenes, as S3 | 733 |
| S6 | 12 | empty table with non-target objects only | 0 |

S6 has no labels on purpose: background images teach the model that other objects on the table are not targets.

The first plan also had separate sessions for low light, very bright light and hard cases on other backgrounds. They were not captured as separate sessions; there was no light source strong enough for an over-exposure session, so brightness robustness relies partly on YOLOv5's HSV augmentation. This is a known limitation, and the hard cases below are candidates for a new session S7.

### Hard cases (planned)

- **Clutter:** many objects close together, random orientations.
- **Distractors:** everyday objects that are *not* targets (cup, ball, pen, a yellow object). They are not labeled, so the model learns "round and colored" is not enough.
- **Occlusion:** objects behind or on top of each other, partly covered, cut by the image edge.
- **Backgrounds:** white sheet, dark cloth, patterned cloth. Every class appears on every background, so no class gets tied to one color.

Each object must still be recognizable by a person; otherwise it is noise, not a hard case.

## Train / validation split

Photos from the same session look alike. A random split would put near-duplicates in both sets and inflate the score. The split for the robot's detector is therefore **by whole session**: **S4** is the validation set (a typical scene with all five classes), all other sessions are training data. Only the helper model `annotation01` used a mixed split; see [training.md](training.md).

## File naming

The capture tool numbers files from 1 in every session, so the same file name appears in each session folder. Before labeling, every image is copied into one flat folder with its session as a prefix:

```
S1_head_000001.png, S1_head_000002.png, ..., S2_head_000001.png, ...
```

Raw session folders are kept untouched as the original copy.

## Totals

295 images, 1 823 boxes: apple 432, potato 420, pepper 412, banana 377, battery 182.
