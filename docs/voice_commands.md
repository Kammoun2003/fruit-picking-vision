# Voice command spec v1

The voice assistant turns a spoken or typed sentence into **one validated command** for the robot. The LLM only translates language into a command; it never sees the table and never controls the robot directly.

```
speech → text → shortcuts (stop / status) → LLM → JSON → strict check → human confirmation → robot API
                                                                                                │
                                         robot: YOLO detections in the work area → pick → place ┘
```

## Table layout

```
   [banana box] [pepper box] [potato box] [apple box]     [waste bin]
                       ┌──────────────────────┐
                       │      work area       │            [hand-over zone]
                       └──────────────────────┘
```

- The boxes, the waste bin and the hand-over zone are **outside the head camera's view**, at fixed, marked positions within the arm's reach.
- Each destination is a **taught arm pose**, not a detected object. No "box" class is trained.
- The robot only uses detections whose box center lies inside the **work area** (a fixed pixel rectangle). This also protects against an object at the table edge or a box pushed into view.

| Class | Destination |
|---|---|
| banana, pepper, potato, apple | its own box |
| battery (intruder) | waste bin |

## Commands

| Command | `object` | Meaning | Motion → needs confirmation |
|---|---|---|---|
| `START_AUTO` | `null` | **Main task:** sort everything in the work area, each item to its destination | yes |
| `SORT` | banana, pepper, potato or apple | Sort only that class into its box | yes |
| `REMOVE` | battery | Take the intruders off the table into the waste bin | yes |
| `PICK` | banana, pepper, potato or apple | Bring one item of that class to the hand-over zone | yes |
| `COUNT` | any of the 5 classes, or `null` for everything | How many are in the work area; the **robot** answers with the YOLO count | no |
| `START_SINGLE` | `null` | Sort one item of any class | yes |
| `STATUS` | `null` | Robot state | no |
| `STOP` | `null` | Software stop; cancels any pending confirmation | no |
| `NONE` | `null` | Conversation, or anything not allowed | no |

`stop` / `停止` and `status` / `查询状态`, typed exactly, bypass the LLM.

## JSON returned by the LLM

Always exactly three keys:

```json
{"command": "PICK", "object": "banana", "reply": "OK, I'll bring you a banana."}
{"command": "COUNT", "object": null, "reply": "Let me check what is on the table."}
{"command": "NONE", "object": null, "reply": "I can only handle banana, pepper, potato, apple or battery."}
```

## Rules

| Rule | Example |
|---|---|
| `object` is always a class name, never a synonym | "bell pepper", 辣椒, 青椒 → `pepper`; 土豆, 马铃薯 → `potato` |
| `SORT` and `PICK` only take a food class | "give me the battery" → `REMOVE battery` |
| `REMOVE` only takes `battery` | "remove the apple" → `NONE` (reply: did you mean sort the apples?) |
| Every other command has `object: null` | |
| Unknown object → `NONE` | "give me an orange", "sort the cups" |
| Two objects in one sentence → `NONE` | "give me the apple and the banana" (reply: one object at a time) |
| …except for counting: several classes → `COUNT` with `object: null` | "how many apples and bananas?" — the robot reports every class, which answers the question and moves nothing |
| Negation → `NONE` | "don't sort the bananas" |
| Unclear reference → `NONE` | "give me that one", "sort it" |
| `reply` never claims an action is done | ✗ "I gave you the apple" ✓ "I'll bring you an apple" |
| `reply` never states a count | ✗ "There are 3 apples" ✓ "Let me check the apples" |
| `reply` uses the language of the request | English request → English reply |

The application rejects any answer that breaks these rules, and then sends nothing.

## What the robot side must support

1. A command API that accepts `command` and `object`.
2. Taught poses for the 4 boxes, the waste bin and the hand-over zone.
3. `SORT`, `PICK`, `REMOVE`: run YOLO, keep only detections of that class inside the work area, pick one (the most confident or the closest).
4. `COUNT`: return the number of detections per class inside the work area.
5. A clear answer when nothing matches ("no banana found"), without moving.

## Evaluation

The test set is [tests/intent_test_set.csv](../tests/intent_test_set.csv): 60 sentences in English and Chinese, each with the expected command and object.

| Metric | Definition |
|---|---|
| Command accuracy | predicted command = expected command |
| Exact match | command **and** object both correct |
| **Unsafe errors** | a motion command (`START_AUTO`, `SORT`, `REMOVE`, `PICK`, `START_SINGLE`) predicted where `NONE` or a non-motion command was expected |
| Missed commands | `NONE` predicted where a real command was expected |

Each run also records the **latency** of every LLM call (median and maximum, in seconds); shortcuts are excluded because they never reach the LLM.

Results are reported per language and per group. Unsafe errors matter most: a missed command only annoys the user, while an unsafe error moves the robot when it should not. Every motion still needs a human confirmation, so this is a second line of defence, not the only one.
