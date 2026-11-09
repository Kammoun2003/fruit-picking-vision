# Detector module

`fruit_detector.py` loads a trained YOLOv5 model once and returns detections as Python objects, so robot code can use them frame by frame without reading files. It is the interface between this repository and the grasping side (depth, 3D localization, camera-to-robot transform, motion).

## Setup

The weights and the YOLOv5 code are not stored in git. Next to `fruit_detector.py`:

```
detector/
├── fruit_detector.py
├── weights/fruit01_best.pt     # runs/fruit01/weights/best.pt from training
└── yolov5/                     # the YOLOv5 code the model was trained with
```

Other locations can be passed: `FruitDetector(weights=..., yolov5_dir=...)`.

## Usage

```python
from fruit_detector import FruitDetector

detector = FruitDetector()                 # once at startup; device='' picks the GPU if available
detections = detector.detect(color_image)  # every frame: BGR uint8 numpy array (H, W, 3)
```

Each detection is a dict, sorted by confidence:

```python
{'class_id': 3, 'class_name': 'apple', 'confidence': 0.9704, 'bbox': [499, 365, 664, 531]}
```

- `bbox` = `[x_min, y_min, x_max, y_max]` in **pixels of the original input image**. The network runs at 640 internally; boxes are scaled back, so they can be used directly on a depth image aligned to color.
- `conf` (default 0.25) and `iou` (default 0.45) are the usual YOLOv5 thresholds.
- Classes come from the checkpoint: `0 banana, 1 pepper, 2 potato, 3 apple, 4 battery`. One `banana` box covers a whole bunch, as labeled.

Command-line check without a camera:

```bash
python fruit_detector.py --source path/to/image_or_folder --save out_dir
```

### With a RealSense camera

```python
import numpy as np
import pyrealsense2 as rs
from fruit_detector import FruitDetector

pipeline, config = rs.pipeline(), rs.config()
config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 15)
config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 15)
pipeline.start(config)
align = rs.align(rs.stream.color)       # depth pixels now match color pixels
detector = FruitDetector()

frames = align.process(pipeline.wait_for_frames())
color = np.asanyarray(frames.get_color_frame().get_data())
depth = frames.get_depth_frame()
for d in detector.detect(color):
    x1, y1, x2, y2 = d['bbox']
    u, v = (x1 + x2) // 2, (y1 + y2) // 2
    print(d['class_name'], d['confidence'], (u, v), depth.get_distance(u, v))
```

The box center is not always on the object (a banana bunch, an object partly behind another). A median of valid depths in the central part of the box is more robust than a single pixel.

## Check on unseen data

Run on session S4 (51 images, 462 objects, never used for training), matching each detection to a hand label of the same class with IoU ≥ 0.5:

| | |
|---|---|
| correct / false / missed | 454 / 5 / 8 |
| precision / recall | 0.989 / 0.983 |
| mean IoU with the hand labels | 0.93 |
| time per 1280×720 image | ~13 ms on a GTX 1650 Ti (4 GB), ~77 ms on CPU |

The mean IoU of 0.93 also confirms that the boxes are in original-image pixels. The first call after loading is slower (warm-up).

## Requirements

Tested with Python 3.10, torch 2.6 (CUDA 12.4), torchvision 0.21, numpy 2.2, OpenCV, Pillow, PyYAML and `ultralytics>=8.4.164`, which the YOLOv5 version used here imports. Not yet tested on the robot computer.

`fruit_detector.py` adds `yolov5/` to `sys.path`; YOLOv5's packages are called `models` and `utils`, which can clash with modules of the same name in the calling project.
