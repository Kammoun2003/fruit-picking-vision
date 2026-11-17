"""Tests for the reference-point analysis with synthetic arm positions (no camera, no arm).

    python robot/test_refpoint_check.py
"""
import csv
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from refpoint_check import FIELDS, analyze  # noqa: E402

# Camera positions measured on the real table (2026-11-16)
CAMERA = {'centre': (-0.0748, -0.3793, -0.3055), 'back-left': (0.0873, -0.5364, -0.3058),
          'back-right': (-0.2041, -0.5448, -0.2935), 'front-left': (0.103, -0.3509, -0.2859)}


def rows(arm_of):
    """Rows with the arm tip computed from the camera position by arm_of(x, y) -> (x, y)."""
    out = []
    for label, (x, y, z) in CAMERA.items():
        ax, ay = arm_of(x, y)
        out.append(dict(zip(FIELDS, [label, 'apple', x, y, z, ax, ay, z + 0.03])))
    return out


class AnalyzeTest(unittest.TestCase):
    def test_small_errors_are_good(self):
        result = analyze(rows(lambda x, y: (x + 0.003, y - 0.004)))
        self.assertTrue(result['summary'].startswith('GOOD'))
        self.assertAlmostEqual(result['max_xy'], 0.005, places=6)

    def test_constant_offset_is_recognised(self):
        result = analyze(rows(lambda x, y: (x - 0.025, y + 0.010)))
        self.assertTrue(result['summary'].startswith('CONSTANT OFFSET'), result['summary'])
        ox, oy = result['mean_offset']
        self.assertAlmostEqual(ox, 0.025, places=6)
        self.assertAlmostEqual(oy, -0.010, places=6)
        self.assertLess(result['max_residual'], 1e-9)

    def test_rotation_is_a_varying_error(self):
        a = math.radians(8)  # a calibration rotated by 8 degrees around the vertical axis
        result = analyze(rows(lambda x, y: (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))))
        self.assertTrue(result['summary'].startswith('VARYING'), result['summary'])

    def test_dz_is_listed_not_judged(self):
        result = analyze(rows(lambda x, y: (x, y)))
        self.assertTrue(result['summary'].startswith('GOOD'))
        self.assertAlmostEqual(result['points'][0]['dz'], -0.03, places=6)

    def test_report_from_saved_file(self):
        path = Path(tempfile.mkdtemp()) / 'refpoints.csv'
        with open(path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows(lambda x, y: (x - 0.025, y)))
        out = subprocess.run([sys.executable, str(HERE / 'refpoint_check.py'), '--report', str(path)],
                             capture_output=True, text=True, encoding='utf-8', check=True).stdout
        self.assertIn('CONSTANT OFFSET', out)
        self.assertIn('centre', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
