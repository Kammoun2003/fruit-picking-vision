"""Fruit positions in the robot World frame: YOLOv5 box -> aligned depth -> camera 3D point -> World.

    from fruit_localizer import FruitLocalizer, load_transform
    localizer = FruitLocalizer(load_transform('calibration_result.json'))
    fruits = localizer.locate(color_bgr, depth_m, intrinsics)
    # [{'class_name': 'apple', 'confidence': 0.96, 'xyz_world': [x, y, z], ...}, ...]

Steps for every detection:
1. box centre (u, v) in pixels of the color image;
2. depth = median of the valid depths in the central part of the box (depth aligned to color, metres);
3. camera point P_camera from (u, v, depth) and the color-stream intrinsics (RealSense optical frame:
   x right, y down, z forward);
4. P_world = T_world_camera @ P_camera, with the 4x4 matrix from the head-camera calibration.
Detections without enough valid depth are skipped instead of returning a wrong position.

Live view (reads the camera only; nothing moves):
    python fruit_localizer.py --calibration <result.json> [--serial <head camera serial>]
    keys: p = print the current list, q = quit.   --once: print one frame as JSON and exit.

The calibration is preliminary: do not command the arm with these coordinates before they have been
checked against known reference points.
"""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time

import numpy as np

from fruit_detector import FruitDetector

DEPTH_RANGE_M = (0.10, 3.00)  # RealSense D435 working range; values outside are treated as invalid


@dataclass
class Intrinsics:
    """Pinhole intrinsics of the color stream (same fields as pyrealsense2.intrinsics)."""
    fx: float
    fy: float
    ppx: float
    ppy: float
    coeffs: tuple = (0.0, 0.0, 0.0, 0.0, 0.0)


def load_transform(path, key='T_world_camera'):
    """Read the 4x4 camera-to-World matrix and check that it is a rigid transform."""
    T = np.asarray(json.loads(Path(path).read_text(encoding='utf-8'))[key], dtype=float)
    if T.shape != (4, 4) or not np.allclose(T[3], [0, 0, 0, 1], atol=1e-6):
        raise ValueError(f'{key} must be a 4x4 homogeneous matrix with last row [0, 0, 0, 1]')
    R = T[:3, :3]
    if not np.allclose(R @ R.T, np.eye(3), atol=1e-3) or abs(np.linalg.det(R) - 1) > 1e-3:
        raise ValueError(f'{key}: the rotation part is not a proper rotation matrix')
    return T


def box_depth(depth_m, bbox, fraction=0.3, min_pixels=10):
    """Median valid depth (metres) in the central `fraction` of the box, or None."""
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    hw, hh = max(1.0, (x2 - x1) * fraction / 2), max(1.0, (y2 - y1) * fraction / 2)
    h, w = depth_m.shape
    patch = depth_m[max(0, int(cy - hh)):min(h, int(cy + hh) + 1), max(0, int(cx - hw)):min(w, int(cx + hw) + 1)]
    valid = patch[(patch > DEPTH_RANGE_M[0]) & (patch < DEPTH_RANGE_M[1])]
    return float(np.median(valid)) if valid.size >= min_pixels else None


def deproject(intrinsics, u, v, z):
    """Pixel (u, v) at depth z (metres) -> 3D point in the camera optical frame."""
    if any(abs(c) > 1e-9 for c in intrinsics.coeffs):
        import pyrealsense2 as rs  # the stream has lens distortion: let RealSense handle the model
        return np.array(rs.rs2_deproject_pixel_to_point(intrinsics, [float(u), float(v)], float(z)))
    return np.array([(u - intrinsics.ppx) * z / intrinsics.fx, (v - intrinsics.ppy) * z / intrinsics.fy, z])


def camera_to_world(T_world_camera, p_camera):
    return (T_world_camera @ np.append(p_camera, 1.0))[:3]


class FruitLocalizer:
    def __init__(self, T_world_camera, detector=None, **detector_args):
        self.T = np.asarray(T_world_camera, dtype=float)
        self.detector = detector or FruitDetector(**detector_args)

    def locate(self, color_bgr, depth_m, intrinsics):
        """Detections with World coordinates. depth_m: depth aligned to color, in metres, same size as color."""
        if depth_m.shape != color_bgr.shape[:2]:
            raise ValueError('Depth must be aligned to color (same image size)')
        fruits = []
        for d in self.detector.detect(color_bgr):
            x1, y1, x2, y2 = d['bbox']
            u, v = (x1 + x2) / 2, (y1 + y2) / 2
            z = box_depth(depth_m, d['bbox'])
            if z is None:
                continue  # no reliable depth: skip rather than return a wrong position
            p_camera = deproject(intrinsics, u, v, z)
            p_world = camera_to_world(self.T, p_camera)
            fruits.append(dict(d, uv=[round(u, 1), round(v, 1)], depth_m=round(z, 4),
                               xyz_camera=[round(float(c), 4) for c in p_camera],
                               xyz_world=[round(float(c), 4) for c in p_world]))
        return fruits


def main():
    import cv2
    import pyrealsense2 as rs
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--calibration', required=True, help='JSON file containing T_world_camera')
    p.add_argument('--serial', help='RealSense serial number (default: first camera found)')
    p.add_argument('--conf', type=float, default=0.25)
    p.add_argument('--once', action='store_true', help='print one frame as JSON and exit, no window')
    a = p.parse_args()

    localizer = FruitLocalizer(load_transform(a.calibration), conf=a.conf)
    pipeline, config = rs.pipeline(), rs.config()
    if a.serial:
        config.enable_device(a.serial)
    config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 15)
    config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 15)
    profile = pipeline.start(config)
    depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
    align = rs.align(rs.stream.color)  # depth pixels now match color pixels
    try:
        for _ in range(15):  # let auto-exposure settle
            pipeline.wait_for_frames()
        while True:
            frames = align.process(pipeline.wait_for_frames())
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth:
                continue
            intrinsics = color.profile.as_video_stream_profile().intrinsics
            image = np.asanyarray(color.get_data())
            depth_m = np.asanyarray(depth.get_data()).astype(np.float32) * depth_scale
            start = time.perf_counter()
            fruits = localizer.locate(image, depth_m, intrinsics)
            ms = 1000 * (time.perf_counter() - start)
            if a.once:
                print(json.dumps(fruits, indent=2))
                break
            for f in fruits:
                x1, y1, x2, y2 = f['bbox']
                X, Y, Z = f['xyz_world']
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.circle(image, (int(f['uv'][0]), int(f['uv'][1])), 4, (0, 255, 0), -1)
                cv2.putText(image, f"{f['class_name']} {f['confidence']:.2f}", (x1, max(y1 - 26, 16)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.putText(image, f'X {X:+.3f} Y {Y:+.3f} Z {Z:+.3f} m', (x1, max(y1 - 6, 34)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
            cv2.putText(image, f'{len(fruits)} located  {ms:.0f} ms  World frame, PRELIMINARY calibration',
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow('fruit01 World XYZ (p = print, q = quit)', image)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('p'):
                print(json.dumps(fruits, indent=2), flush=True)
            elif key == ord('q'):
                break
    finally:
        pipeline.stop()
        if not a.once:
            cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
