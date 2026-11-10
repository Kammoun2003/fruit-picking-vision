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

## Live view

`live_demo.py` opens a window with the live RealSense image, the detections and the depth at each box centre (`apple 0.96 0.74m`). It only reads the camera.

```bash
python live_demo.py                      # first RealSense camera found
python live_demo.py --serial <serial>    # a specific camera, e.g. the head camera
```

## Requirements

Laptop (training and tests): Python 3.10, torch 2.6 (CUDA 12.4), torchvision 0.21, numpy 2.2, OpenCV, Pillow, PyYAML and `ultralytics>=8.4.164`, which the YOLOv5 version used here imports.

### Running on the robot (Jetson AGX Orin)

The robot runs Ubuntu 20.04, Python 3.8 and NVIDIA's Jetson build of PyTorch 2.1 (CUDA). That PyTorch must not be replaced, and the robot is shared with another project, so nothing is installed system-wide. A virtual environment reuses the system PyTorch, and `ultralytics` is installed without its dependencies (they would pull a PyTorch without GPU support):

```bash
python3 -m venv --system-site-packages ~/fruit_env
source ~/fruit_env/bin/activate
python -m pip install --upgrade pip              # Ubuntu 20.04's pip is too old for some options
pip install --no-deps "ultralytics==8.4.183"
python -c "import torch, ultralytics; print(torch.__version__, torch.cuda.is_available(), ultralytics.__version__)"
```

All other libraries were already installed; `polars` is not needed for detection. Before running, keep the Ultralytics settings inside the project folder instead of the shared user folder:

```bash
export YOLO_CONFIG_DIR=$PWD/.ultralytics YOLO_OFFLINE=true
```

Two problems met on the robot, both handled in `fruit_detector.py`:

| Symptom | Cause | Handling |
|---|---|---|
| `cannot instantiate 'WindowsPath' on your system` | the model was trained on Windows; the checkpoint stores Windows path objects | on Linux, `WindowsPath` is mapped to `PosixPath` before loading |
| YOLOv5 runs `pip install -U ultralytics` by itself | this YOLOv5 version does that when `ultralytics` cannot be imported | `FruitDetector` stops first with a clear message |

Result: the model loads on the Orin's GPU and detects correctly on head-camera images.

`fruit_detector.py` adds `yolov5/` to `sys.path`; YOLOv5's packages are called `models` and `utils`, which can clash with modules of the same name in the calling project.
