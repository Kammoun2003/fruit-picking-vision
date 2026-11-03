# Experiment log

One entry per training run. Every run gets a new name; old runs are never overwritten.

## Planned runs

| Run | Question it answers |
|---|---|
| `annotation01` | Is a model trained on the seed set (S1 + S2) good enough to pre-label the other sessions? |
| `fruit01` | Main detector, trained on all reviewed sessions, validated on whole held-out sessions |
| `fruit01_25` / `_50` / `_100` | How does validation mAP grow with the amount of training data? |
| low-light test | How much does `fruit01` drop on the darker session? |

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
