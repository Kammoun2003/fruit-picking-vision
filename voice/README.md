# Voice intents

Turns a sentence into one validated command for the fruit robot, following [docs/voice_commands.md](../docs/voice_commands.md). Standard library only (Python 3.8+).

| File | Role |
|---|---|
| `intent.py` | allowed commands and classes, the LLM system prompt, the strict answer check (`parse_intent`), the reply-language guard (`match_language`), the stop/status shortcuts, one OpenAI-compatible API call |
| `evaluate.py` | runs [tests/intent_test_set.csv](../tests/intent_test_set.csv) through the LLM and scores it |
| `robot_bridge.py` | runs a validated command on the robot's action API as a sequence of checked steps, stoppable between steps |
| `robot_places.json` | destination name for each class and the hand-over place (placeholders until the robot side confirms them) |
| `mock_robot.py` | fake robot answering like the real action API, to test without the robot |
| `test_robot_bridge.py` | tests of every plan, the error cases and STOP, against the mock robot over HTTP |

## Offline self-test (no key needed)

Checks that the validator accepts correct answers, rejects wrong ones (e.g. `PICK battery`, `REMOVE apple`, extra keys, plain text), that only the exact stop/status phrases skip the LLM, and that a reply in the wrong language is replaced while the command and object stay unchanged.

```bat
python voice\evaluate.py --selftest
```

Expected: `Self-test: 27/27 passed`.

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
| model_wrong_language | the model replied in the other language (the guard then replaced the reply) |
| reply_wrong_language | replies still in the wrong language after the guard (should be 0) |

## Using it in the web demo

The lab's voice/text web demo is not part of this repository. In a local copy, its `understand()` step can import this module so the page shows the new commands (for example `PICK · apple`) with the same validation, and queries (`STATUS`, `STOP`, `COUNT`) run without a confirmation while every motion still needs one.

## From a command to robot actions (`robot_bridge.py`)

The robot does not understand `PICK apple`. Its existing interface (from the earlier battery-sorting project) is one route, `POST <robot>:5000/action`, with small methods:

```json
{"method": "grasp_object", "parameters": {"object_name": "apple"}}
```

The bridge turns each command into a sequence of these methods and checks every reply before sending the next one:

| Command | Robot calls |
|---|---|
| `STATUS` | `query_work_mode` (+ the state of the last task) |
| `COUNT x` / `COUNT` | `detect_objects`, then count `x` (or every class) |
| `PICK x` | `set_work_mode(manual)` → `grasp_object(x)` → `move_object_to(x, hand_over)` |
| `REMOVE battery` | `set_work_mode(manual)` → `grasp_object(battery)` → `move_object_to(battery, waste bin)` |
| `SORT x` | `set_work_mode(manual)`, then up to 10 times: `check_object_exist(x)` → grasp → `move_object_to(x, box of x)` |
| `START_SINGLE` | `set_work_mode(manual)` → `detect_objects` → grasp one object (intruders first) → its destination |
| `START_AUTO` | `set_work_mode(auto)` → `start_work` (the robot's own sorting) |
| `STOP` | cancel the running task before its next step, then `suspend_work` |

Safety rules:

- **Checked replies.** A failed grasp (`[false, 1]` = object not there, `[false, 2]` = automatic mode) ends the task with a clear message; the move is never sent after a failed grasp.
- **Background tasks.** Motions run in a background thread, so the web page stays responsive and STOP is always accepted. Only one task runs at a time; a second motion is refused.
- **Limits.** `SORT` stops after 10 objects per command; every call has a timeout (10 s for queries, 120 s for a grasp or a move); nothing is retried automatically.
- **Honest results.** "accepted" or "moved" means the robot accepted the request, not that the camera verified the result.
- **Software stop is not an emergency stop.** The robot's `suspend_work` lets the current motion finish; the physical emergency stop stays essential.

The destination names (`to`) come from `robot_places.json`, so only that file changes once the robot side confirms the real names.

### Testing without the robot

```bat
python voice\test_robot_bridge.py
```

17 tests against the mock robot over real HTTP: every plan, a missing object, the SORT limit, an empty table, STOP during a task, a second task while one runs, refused command/object combinations, an unreachable robot and an unknown method.

To try the whole chain by hand, start the mock robot (it prints every call it receives):

```bat
python voice\mock_robot.py --objects apple=2,banana=1,battery=1 --delay 1
```

and in the web demo's `.env` set `ROBOT_ENABLED=true`, `ROBOT_API=action`, `ROBOT_BASE_URL=http://127.0.0.1:5000`. Then "give me the apple" + Confirm shows `set_work_mode → grasp_object(apple) → move_object_to(apple, hand_over)` in the mock robot's window; the Status button shows the task progress.

### Open points on the robot side

The bridge assumes the robot program behind `/action` behaves like in the battery project. Still to confirm on the real robot: that it knows the five fruit classes (with this repository's detector), which destination names `move_object_to` accepts, and the exact replies of `move_object_to` and `check_object_exist`.
