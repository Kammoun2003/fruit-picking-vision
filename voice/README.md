# Voice intents

Turns a sentence into one validated command for the fruit robot, following [docs/voice_commands.md](../docs/voice_commands.md). Standard library only (Python 3.8+).

| File | Role |
|---|---|
| `intent.py` | allowed commands and classes, the LLM system prompt, the strict answer check (`parse_intent`), the stop/status shortcuts, one OpenAI-compatible API call |
| `evaluate.py` | runs [tests/intent_test_set.csv](../tests/intent_test_set.csv) through the LLM and scores it |

## Offline self-test (no key needed)

Checks that the validator accepts correct answers, rejects wrong ones (e.g. `PICK battery`, `REMOVE apple`, extra keys, plain text) and that only the exact stop/status phrases skip the LLM.

```bat
python voice\evaluate.py --selftest
```

Expected: `Self-test: 23/23 passed`.

## Evaluation with an LLM

1. Copy `.env.example` to `.env` in the repository root (`.env` is git-ignored) and fill in the API key and model ID. Any OpenAI-compatible chat API works; for providers other than Volcengine Ark, change `ARK_BASE_URL` and set `LLM_THINKING=auto`.
2. Try a few sentences first, then the full set:

```bat
python voice\evaluate.py --limit 5
python voice\evaluate.py
```

The script stops after the first sentence if the API call fails, so a wrong key does not cost a full run. Requests use `temperature=0` so repeated runs are comparable.

Other options:

```bat
python voice\evaluate.py --tests tests\intent_holdout_set.csv          # the unseen hold-out set
python voice\evaluate.py --model doubao-seed-2-0-mini-260428           # another model, same .env
```

Use the hold-out set only to measure, never to tune the prompt; otherwise it stops being unseen.

Each run writes `results/intent_<model>_<time>.csv` (every sentence with the expected and predicted command, object and reply) and a `.json` summary with the scores overall, per language and per group:

| Score | Meaning |
|---|---|
| command | predicted command is correct |
| exact | command and object are both correct |
| unsafe | a motion command was predicted where no motion was expected |
| missed | no usable command (`NONE` or an invalid answer) where a real command was expected |

## Using it in the web demo

The lab's voice/text web demo is not part of this repository. In a local copy, its `understand()` step can import this module so the page shows the new commands (for example `PICK · apple`) with the same validation, and queries (`STATUS`, `STOP`, `COUNT`) run without a confirmation while every motion still needs one.
