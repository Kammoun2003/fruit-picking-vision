# Labeling guide

Tool: LabelImg, format **Pascal VOC XML** (converted to YOLO TXT afterwards). The same rules apply to hand labeling and to reviewing pre-labeled boxes.

## Rules

1. **Label every recognizable target object.** A forgotten object teaches the model that it is background; this is the worst labeling mistake.
2. **Tight boxes**: the box edges touch the object's edges, with nothing cut off and no extra table.
3. **One box per object**, even when objects touch and the boxes overlap.
4. **Partly hidden object** → box only the visible part. If less than about 20–30 % is visible and a person cannot tell what it is, do not label it.
5. **Object cut by the image edge** → label it if it is recognizable; box the part inside the image.
6. **Curved objects** (banana): the box covers the whole curve, even if it contains table.
7. **Distractors are never labeled.** Only the target classes and the intruder class get boxes.
8. **Empty images are saved too** (an XML with no objects), so the converter knows they are background, not forgotten.
9. **Check the class before moving on.** A wrong class is worse than a slightly loose box.
10. **Be consistent.** The same situation always gets the same decision; any new rule is written down here.

## Workflow

1. Label a **seed set** by hand (sessions S1 + S2, about 100 images, spread over all classes).
2. Convert XML → YOLO TXT; the converter also checks names, image sizes, unknown classes and boxes outside the image.
3. Train a first detector on the seed set and use it as an **annotation assistant**: it proposes boxes for the remaining sessions.
4. **Review every proposed box** by hand. Pre-labels are suggestions, not ground truth.
5. Retrain with the reviewed data and repeat if needed.

## LabelImg keys

| Key | Action |
|---|---|
| W | draw a box |
| D / A | next / previous image |
| Ctrl+S | save |
| Del | delete the selected box |
| Ctrl+D | duplicate the selected box |
| Ctrl + wheel | zoom |

Turn on *View → Auto Save mode* so moving to the next image saves the current one.

## Notes from the review

- A **bunch of bananas** is one object and gets one box, as for the other classes.
- Two separate objects that touch still get two boxes. The helper model sometimes drew one box around two touching objects; such boxes were split.
- The helper model proposed batteries as pepper or potato, because it had never seen one; every battery was checked by hand.

## Labeling result

| Set | Images | apple | potato | pepper | banana | battery |
|---|---|---|---|---|---|---|
| seed (S1 + S2, by hand) | 100 | 57 | 52 | 49 | 12 | 0 |
| S3–S6 (pre-labeled, reviewed) | 195 | 375 | 368 | 363 | 365 | 182 |
| **total** | **295** | **432** | **420** | **412** | **377** | **182** |
