"""Live RealSense view with fruit01 detections and the depth at each box centre. Press q to quit.

    python live_demo.py                      # first RealSense camera found
    python live_demo.py --serial <serial>    # a specific camera, e.g. the head camera

Only reads the camera; nothing moves.
"""
import argparse
import time

import cv2
import numpy as np
import pyrealsense2 as rs

from fruit_detector import FruitDetector

COLORS = {'banana': (0, 220, 255), 'pepper': (0, 0, 255), 'potato': (60, 140, 200),
          'apple': (0, 200, 0), 'battery': (255, 0, 255)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--serial', help='RealSense serial number (default: first camera found)')
    p.add_argument('--conf', type=float, default=0.25)
    a = p.parse_args()

    detector = FruitDetector(conf=a.conf)
    pipeline, config = rs.pipeline(), rs.config()
    if a.serial:
        config.enable_device(a.serial)
    config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 15)
    config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 15)
    pipeline.start(config)
    align = rs.align(rs.stream.color)  # depth pixels now match color pixels
    try:
        while True:
            frames = align.process(pipeline.wait_for_frames())
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth:
                continue
            image = np.asanyarray(color.get_data())
            start = time.perf_counter()
            detections = detector.detect(image)
            ms = 1000 * (time.perf_counter() - start)
            for d in detections:
                x1, y1, x2, y2 = d['bbox']
                u, v = (x1 + x2) // 2, (y1 + y2) // 2
                c = COLORS.get(d['class_name'], (255, 255, 255))
                cv2.rectangle(image, (x1, y1), (x2, y2), c, 2)
                cv2.circle(image, (u, v), 4, c, -1)
                cv2.putText(image, f"{d['class_name']} {d['confidence']:.2f} {depth.get_distance(u, v):.2f}m",
                            (x1, max(y1 - 8, 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
            cv2.putText(image, f'{len(detections)} objects  {ms:.0f} ms', (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.imshow('fruit01 live (q = quit)', image)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
