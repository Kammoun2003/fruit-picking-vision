# Dataset scripts

Small one-off scripts used to build the datasets. Paths at the top of each script point to my local folders; adjust them before reuse. Each script refuses to write into an existing output folder, so nothing is overwritten.

| Script | What it does |
|---|---|
| `split_seed.py` | copies the 100 seed images (S1 + S2) and their YOLO labels into `dataset/`: every 5th image → val, the rest → train (80 / 20) |
| `collect_sessions.py` | copies S3–S6 from the raw capture folders into one flat folder, adding the session prefix (`S3_head_000001.png`) |
| `build_fruit01.py` | builds `dataset_fruit01/` with **whole sessions** per split (S4 → val, all others → train) and writes `data.yaml` from `classes.txt` |

`split_seed.py` and `build_fruit01.py` are run from the folder of the YOLOv5 training package, next to its `classes.txt`. See [docs/training.md](../docs/training.md) for the full sequence.
