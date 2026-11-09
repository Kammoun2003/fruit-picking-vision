"""Fruit detector (YOLOv5, model fruit01) returning detections as Python objects.

    from fruit_detector import FruitDetector
    detector = FruitDetector()                  # load once at startup
    detections = detector.detect(color_image)   # every frame: BGR numpy array (H, W, 3)
    # [{'class_id': 3, 'class_name': 'apple', 'confidence': 0.95, 'bbox': [526, 163, 623, 339]}, ...]

bbox is [x_min, y_min, x_max, y_max] in pixels of the ORIGINAL input image (e.g. 1280x720),
not of the 640 network input. Classes: 0 banana, 1 pepper, 2 potato, 3 apple, 4 battery.

Command-line check on images (no camera needed):
    python fruit_detector.py --source path/to/image_or_folder [--save out_dir]
"""
import argparse
from pathlib import Path
import sys
import time

import numpy as np
import torch

HERE = Path(__file__).resolve().parent


class FruitDetector:
    def __init__(self, weights=HERE / 'weights' / 'fruit01_best.pt', yolov5_dir=HERE / 'yolov5',
                 device='', conf=0.25, iou=0.45, imgsz=640, max_det=100):
        """device: '' = first GPU if available else CPU, or '0', 'cpu'. conf: minimum confidence."""
        # YOLOv5 is imported from its own folder; its packages are called 'models' and 'utils'.
        sys.path.insert(0, str(Path(yolov5_dir).resolve()))
        from models.common import DetectMultiBackend
        from utils.augmentations import letterbox
        from utils.general import check_img_size, non_max_suppression, scale_boxes
        from utils.torch_utils import select_device
        self._letterbox, self._nms, self._scale_boxes = letterbox, non_max_suppression, scale_boxes

        self.device = select_device(device)
        self.model = DetectMultiBackend(str(weights), device=self.device, fp16=False)
        self.stride = int(self.model.stride)
        self.imgsz = check_img_size(imgsz, s=self.stride)
        names = self.model.names
        self.names = [names[i] for i in range(len(names))] if isinstance(names, dict) else list(names)
        self.conf, self.iou, self.max_det = conf, iou, max_det
        self.model.warmup(imgsz=(1, 3, self.imgsz, self.imgsz))

    @torch.no_grad()
    def detect(self, bgr_image):
        """Detect objects in one BGR uint8 image (as from OpenCV or RealSense bgr8). Sorted by confidence."""
        if not isinstance(bgr_image, np.ndarray) or bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
            raise ValueError('Expected a BGR image of shape (H, W, 3)')
        # Same preprocessing as YOLOv5 detect.py: keep aspect ratio, pad to a multiple of the stride.
        image = self._letterbox(bgr_image, self.imgsz, stride=self.stride, auto=True)[0]
        image = np.ascontiguousarray(image.transpose((2, 0, 1))[::-1])  # HWC BGR -> CHW RGB
        tensor = torch.from_numpy(image).to(self.device).float()[None] / 255
        det = self._nms(self.model(tensor), self.conf, self.iou, max_det=self.max_det)[0]
        # Map boxes from the network input back to the original image pixels.
        det[:, :4] = self._scale_boxes(tensor.shape[2:], det[:, :4], bgr_image.shape).round()
        return [dict(class_id=int(c), class_name=self.names[int(c)], confidence=round(float(p), 4),
                     bbox=[int(x1), int(y1), int(x2), int(y2)])
                for x1, y1, x2, y2, p, c in det.tolist()]


def main():
    import cv2
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', required=True, help='image file or folder of images')
    p.add_argument('--weights', default=str(HERE / 'weights' / 'fruit01_best.pt'))
    p.add_argument('--device', default='')
    p.add_argument('--conf', type=float, default=0.25)
    p.add_argument('--save', help='folder for images with the boxes drawn (optional)')
    a = p.parse_args()

    source = Path(a.source)
    paths = sorted(q for q in source.iterdir() if q.suffix.lower() in {'.png', '.jpg', '.jpeg', '.bmp'}) \
        if source.is_dir() else [source]
    detector = FruitDetector(a.weights, device=a.device, conf=a.conf)
    print('Classes:', detector.names, '| device:', detector.device)
    if a.save:
        Path(a.save).mkdir(parents=True, exist_ok=True)
    times = []
    for path in paths:
        image = cv2.imread(str(path))
        start = time.perf_counter()
        detections = detector.detect(image)
        times.append(time.perf_counter() - start)
        print(f'{path.name} ({image.shape[1]}x{image.shape[0]}): {len(detections)} objects')
        for d in detections:
            print('   ', d)
        if a.save:
            for d in detections:
                x1, y1, x2, y2 = d['bbox']
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(image, f"{d['class_name']} {d['confidence']:.2f}", (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imwrite(str(Path(a.save) / path.name), image)
    if times:
        print(f'Median time per image: {1000 * float(np.median(times)):.1f} ms')


if __name__ == '__main__':
    main()
