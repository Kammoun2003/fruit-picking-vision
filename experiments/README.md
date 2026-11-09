# Experiment log

One entry per training or evaluation run. Every run gets a new name; old runs are never overwritten.

## Detector runs

| Run | Question it answers | State |
|---|---|---|
| `annotation01` | Is a model trained on the seed set (S1 + S2) good enough to pre-label the other sessions? | ✅ yes, 82 % of its boxes kept unchanged |
| `fruit01` | Main detector, trained on all reviewed sessions, validated on a whole held-out session | ✅ mAP50 0.984 on S4 |
| `fruit02` | Do longer training (150 epochs) and more varied scenes improve box precision? | planned |
| `fruit01` on S7 | Final score on a new session never used for any decision | planned |

How the datasets were built: [docs/training.md](../docs/training.md).

### `annotation01` (2026-11-07)

- **Goal:** helper model to pre-label S3–S6.
- **Data:** seed set S1 + S2, 100 images, mixed split (every 5th image → val): 80 train / 20 val. Boxes: apple 57, potato 52, pepper 49, banana 12, battery 0.
- **Command:** training package defaults, from pretrained YOLOv5s, 100 epochs, batch 4, image size 640.
- **Hardware / time:** GTX 1650 Ti 4 GB, 18 min.

| Class | P | R | mAP50 | mAP50-95 |
|---|---|---|---|---|
| all | 0.987 | 1.000 | 0.995 | 0.907 |
| banana | 0.984 | 1.000 | 0.995 | 0.786 |
| pepper | 0.987 | 1.000 | 0.995 | 0.976 |
| potato | 0.987 | 1.000 | 0.995 | 0.915 |
| apple | 0.990 | 1.000 | 0.995 | 0.951 |

- **Observations:** the val images are neighbouring frames of train images, so these scores are optimistic. Banana has the least precise boxes (9 training boxes). Battery cannot be detected (no training boxes). Curves: [results/annotation01/results.csv](../results/annotation01/results.csv).
- **Next step:** use it to pre-label S3–S6 and measure it by the review.

### Pre-label review (S3–S6)

`annotation01` proposed 1 602 boxes on the 195 images of S3–S6 (confidence ≥ 0.25). Every image was then reviewed by hand. Matching proposals to the final labels (IoU ≥ 0.5):

| Outcome | Boxes | Share of proposals |
|---|---|---|
| kept unchanged (IoU ≥ 0.9) | 1 314 | 82 % |
| box adjusted | 69 | 4 % |
| class changed | 174 | 11 % |
| deleted (false or duplicate) | 45 | 3 % |
| added by hand (missed) | 96 | – |

- **Class changes:** batteries proposed as pepper (116) or potato (34) make up 150 of the 174; the model had never seen a battery. Between the food classes there were only 23 changes (mostly pepper ↔ apple).
- **Missed objects:** potato 53, battery 31, banana 7, apple 4, pepper 1.
- **Duplicates:** 34 objects got two boxes with different classes, because YOLOv5's NMS only merges boxes of the same class.
- **S6** (empty table with non-target objects): all 10 proposals were false and deleted; the 12 images are kept as background examples.
- **Final labels S3–S6:** apple 375, potato 368, banana 365, pepper 363, battery 182.
- **Conclusion:** apart from the unknown battery class, the helper was right about 90 % of the time; reviewing was much faster than drawing.

### `fruit01` (2026-11-08)

- **Goal:** detector for the robot.
- **Data:** all 295 reviewed images. Split by whole session: train S1, S2, S3, S5, S6 (244 images, 1 361 boxes); val **S4** (51 images, 462 boxes: banana 102, pepper 99, potato 101, apple 109, battery 51).
- **Command:** same settings as `annotation01`, again from pretrained YOLOv5s (not from `annotation01`).
- **Hardware / time:** GTX 1650 Ti 4 GB, 54 min; best epoch 97 of 100.

| Class | P | R | mAP50 | mAP50-95 |
|---|---|---|---|---|
| all | 0.991 | 0.985 | 0.984 | 0.876 |
| banana | 0.999 | 0.990 | 0.995 | 0.859 |
| pepper | 0.969 | 1.000 | 0.972 | 0.872 |
| potato | 0.990 | 1.000 | 0.995 | 0.890 |
| apple | 0.999 | 0.936 | 0.962 | 0.905 |
| battery | 0.999 | 1.000 | 0.995 | 0.854 |

- **Observations:**
  - Confusion matrix ([results/fruit01/confusion_matrix.png](../results/fruit01/confusion_matrix.png)): about **6 % of apples are predicted as pepper** and 1 % as potato, hence apple recall 0.94. Few misses (pepper 3 %, banana and potato 1 %), few false boxes on the background (mostly pepper).
  - Battery: 51 / 51 found, no confusion.
  - Slightly lower than `annotation01`, but measured on a whole unseen scene, so much more trustworthy.
  - mAP50-95 was still rising at the end (0.77 at epoch 50 → 0.87 at epoch 100): longer training may give tighter boxes.
  - S4 also selected `best.pt`, so the score is slightly optimistic; no settings were tuned on it.
  - The same model through [detector/fruit_detector.py](../detector/fruit_detector.py) on S4: 454 correct, 5 false, 8 missed, mean IoU 0.93, ~13 ms per image.
- **Next step:** integration on the robot; a new session S7 as the final test; possibly `fruit02`.

## Voice intent runs (2026-11-03)

Model `doubao-seed-2-1-pro-260628` (Volcengine Ark), `temperature=0`, thinking disabled, test set [tests/intent_test_set.csv](../tests/intent_test_set.csv) (60 sentences: 38 EN, 22 ZH). Result files are in [results/](../results/).

| Run | Change | Command acc. | Exact | Unsafe | Missed | Median latency |
|---|---|---|---|---|---|---|
| v1 | first prompt | 96.7 % | 96.7 % | 0 | 1 | not measured |
| v2 | START_SINGLE examples, COUNT for several classes, reply language; test #42 relabelled | 98.3 % | 98.3 % | **1** | 0 | 4.0 s |
| v3 | vague requests ("take something") are NONE | **100 %** | **100 %** | 0 | 0 | 4.5 s (max 13.4 s) |

- **v1 errors:** #12 "抓取一个" → NONE (the model found "grab one" too vague); #42 "How many apples and bananas?" → `COUNT null`, which the test expected as NONE. The spec now allows `COUNT null` for several classes (it moves nothing and answers the question), so #42 was relabelled.
- **v2 error:** the new "pick one object" examples made "Take something." look like `START_SINGLE` — an **unsafe** error, introduced by fixing another one. v3 adds an explicit rule for vague requests.
- **v3 checks beyond the score:** 0 / 56 replies in the wrong language (v1 answered "Give me an orange." in Chinese), 0 COUNT replies stating a number, 0 replies claiming an action was done.
- **Caveat:** the prompt was tuned on this same test set, so 100 % is optimistic. A new, unseen set of sentences is needed for an honest final score.
- **Latency:** 4–5 s median per LLM call is slow for a spoken command. Next: compare a lighter model on the same set.

## Hold-out set and model comparison (2026-11-03/04)

The hold-out set [tests/intent_holdout_set.csv](../tests/intent_holdout_set.csv) has 31 new sentences (18 EN, 13 ZH) written after prompt v3 was frozen. Every model below was run **once** on each set with prompt v3, without any further change.

| Model | Tuning set (60) | Hold-out set (31) | Unsafe | Median latency tuning / hold-out |
|---|---|---|---|---|
| `doubao-seed-2-1-pro-260628` | 60/60 | **31/31** | 0 | 4.5 s / 4.9 s |
| `doubao-seed-2-1-lite-260915` | 59/60 | 30/31 | **1** | 4.8 s / 3.7 s |
| `doubao-seed-2-0-mini-260428` | 60/60 | **31/31** | 0 | **3.1 s / 2.2 s** |

- **Prompt v3 generalises:** 31/31 on sentences it was never tuned on, with the pro model and with the mini model. The 100 % on the tuning set was not only overfitting.
- **lite errors:** "How many batteries are there?" → `NONE` (missed), and "Apple." → `PICK apple` (**unsafe**: a one-word request was treated as a motion).
- **mini** was as accurate as pro and the fastest. It is the candidate for the robot demo.
- `doubao-seed-1-6-flash-250828` and `doubao-1-5-lite-32k-250115` are listed by the API but return HTTP 404 for this account (not activated).
- **Limits:** one run per model and set; latency includes the network and varies over the day. Before choosing mini for good, repeat both runs at another time of day.

## Entry template

### `<run name>`

- **Goal:**
- **Data:** train sessions / val sessions, image and box counts per class
- **Command:**
- **Hardware / time:**

| Class | P | R | mAP50 | mAP50-95 |
|---|---|---|---|---|
| all | | | | |

- **Observations:** weak classes, confusions (confusion matrix), typical misses and false positives
- **Next step:**
