# Experiment log

One entry per training run. Every run gets a new name; old runs are never overwritten.

## Planned runs

| Run | Question it answers |
|---|---|
| `annotation01` | Is a model trained on the seed set (S1 + S2) good enough to pre-label the other sessions? |
| `fruit01` | Main detector, trained on all reviewed sessions, validated on whole held-out sessions |
| `fruit01_25` / `_50` / `_100` | How does validation mAP grow with the amount of training data? |
| low-light test | How much does `fruit01` drop on the darker session? |

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
