# Training the detector

From 295 head-camera images to the model `fruit01`. Training used the lab's YOLOv5 teaching package (not included here) on a laptop with a GTX 1650 Ti (4 GB) and 16 GB RAM, Windows 11, Python 3.10.

## Overview

```
S1 + S2 (100 images) ──label by hand──► seed set ──train──► annotation01 (helper)
                                                                 │ pre-labels
S3–S6 (195 images) ◄──────────────review every box by hand───────┘
        │
all 295 reviewed images ──session split──► train fruit01 ──► detector for the robot
```

Labeling everything by hand would have meant drawing about 1 800 boxes. With the helper model, 1 314 of its 1 602 proposed boxes could be kept unchanged.

## 1. Project setup

The teaching package is written for a 4-class battery project. I worked in a **copy** of it, so the original lesson stays usable and its classroom reset script (which deletes `runs/`) cannot remove my models. In the copy, three places hold the class names and all had to change to the five classes of [configs/classes.txt](../configs/classes.txt):

| Place | Change |
|---|---|
| `classes.txt` (read by the training tool) | five fruit classes |
| `dataset/data.yaml` | same names, same order (the tool refuses a mismatch) |
| annotation tool (`dataset_tools.py`) | names were hard-coded; now read from `classes.txt` |

The model config still says `nc: 4`; YOLOv5 replaces it with the number of names in `data.yaml` ("Overriding model.yaml nc=4 with nc=5").

## 2. Seed set and `annotation01`

1. **Label** S1 + S2 by hand in LabelImg (Pascal VOC): 100 images, 170 boxes ([labeling guide](labeling_guide.md)).
2. **Convert** XML → YOLO TXT. The converter requires one XML per image (also for empty images) and checks names, sizes and boxes.
3. **Split** 80 / 20 with every 5th image in val ([scripts/split_seed.py](../scripts/split_seed.py)). This split mixes S1 and S2 on purpose: with a session split, the val part would contain no banana at all. It is acceptable for a helper whose output is reviewed anyway, but its val score is optimistic (neighbouring frames are in train and val).
4. **Train** from the official pretrained YOLOv5s weights, 100 epochs, batch 4, image size 640.

## 3. Pre-labeling and review

1. Copy S3–S6 into one flat folder with session prefixes ([scripts/collect_sessions.py](../scripts/collect_sessions.py)).
2. Run `annotation01` on them and export the boxes as editable VOC XML (confidence ≥ 0.25).
3. **Review every image** in LabelImg: fix classes, delete false or duplicate boxes, add missed objects, tighten boxes.

The review result is the honest test of the helper model; see the [experiment log](../experiments/README.md#pre-label-review-s3s6).

## 4. `fruit01`

1. Convert the reviewed XML → YOLO TXT.
2. Build the dataset with **whole sessions** per split ([scripts/build_fruit01.py](../scripts/build_fruit01.py)):

   | Split | Sessions | Images | Boxes |
   |---|---|---|---|
   | train | S1, S2, S3, S5, S6 | 244 | 1 361 |
   | val | S4 | 51 | 462 |

   S4 is the only session that is both typical and contains all five classes, so it is the validation session. S6 (empty table with non-target objects) stays in train as background examples.
3. Check the dataset (read-only), then train again **from the pretrained YOLOv5s weights**, not from `annotation01`, so no helper mistakes are inherited. 100 epochs took 54 minutes.

### Why there is no separate test set

With six sessions, holding out a second whole session would remove about 20 % of the training data. No settings were tuned on S4, but YOLOv5 picks `best.pt` by its S4 score, so the reported score is slightly optimistic. A new session captured later (S7) and real robot trials are the planned final test.

## Problems met on Windows

| Symptom | Cause | Fix |
|---|---|---|
| Screen turned black for a moment, then `MemoryError` in many processes | YOLOv5's label scan (`cache_labels`) starts a process pool with up to 8 processes; on Windows each one re-imports torch, scipy and seaborn, which filled the 16 GB RAM (page file 2.4 GB) | in `utils/dataloaders.py`, `Pool(NUM_THREADS)` → `ThreadPool(NUM_THREADS)` for that scan (`ThreadPool` is already imported there) |
| `No module named 'ultralytics'` | a new terminal without the virtual environment, so the global Python ran | activate the environment; `where python` must list the venv first |
| pre-labeling refused: class names do not match | the annotation tool had the four battery names hard-coded | read the names from `classes.txt` |
| `FileExistsError` when building a dataset | the scripts never write into an existing folder | remove the old (empty) folder first |
