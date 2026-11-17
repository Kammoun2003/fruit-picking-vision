"""Reference-point check: camera World XYZ of a fruit vs the arm tip position reported by the controller.

    python refpoint_check.py --calibration <result.json> --serial <head camera serial> --out refpoints.csv
    python refpoint_check.py --report refpoints.csv          # recompute the table from a saved file

At each point: put ONE fruit on the table, press Enter (the camera measures it), move the arm tip
slowly to just above the fruit's centre, type the tip position shown by the controller. The camera
gives the fruit's top surface and the tip stays above it, so X and Y are compared; Z is only listed.
Nothing here moves the arm.
"""
import argparse
import csv
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FIELDS = ['label', 'class_name', 'cam_x', 'cam_y', 'cam_z', 'arm_x', 'arm_y', 'arm_z']


def analyze(rows):
    """Errors camera - arm per point and a short diagnosis. rows: dicts with FIELDS (metres)."""
    points = []
    for r in rows:
        dx, dy = float(r['cam_x']) - float(r['arm_x']), float(r['cam_y']) - float(r['arm_y'])
        points.append(dict(label=r['label'], dx=dx, dy=dy, dz=float(r['cam_z']) - float(r['arm_z']),
                           xy=(dx * dx + dy * dy) ** 0.5, cam=(float(r['cam_x']), float(r['cam_y']))))
    if not points:
        return dict(points=[], summary='no points recorded')
    mean_dx, mean_dy = statistics.mean(p['dx'] for p in points), statistics.mean(p['dy'] for p in points)
    for p in points:  # what is left after removing the common offset
        p['residual'] = ((p['dx'] - mean_dx) ** 2 + (p['dy'] - mean_dy) ** 2) ** 0.5
    xy = [p['xy'] for p in points]
    offset = (mean_dx ** 2 + mean_dy ** 2) ** 0.5
    spread = max(p['residual'] for p in points)
    if max(xy) <= 0.010:
        diagnosis = 'GOOD: every point within 10 mm in X/Y.'
    elif spread <= 0.010:
        diagnosis = (f'CONSTANT OFFSET: the error is almost the same everywhere ({offset * 1000:.0f} mm). '
                     'Likely a tool or frame offset; correct it with one constant shift.')
    else:
        diagnosis = ('VARYING ERROR: the error changes across the table. Check the frames (work frame = '
                     'World?) and the calibration before using the coordinates for grasping.')
    return dict(points=points, n=len(points), mean_xy=statistics.mean(xy), max_xy=max(xy),
                mean_offset=(mean_dx, mean_dy), max_residual=spread, summary=diagnosis)


def report(rows):
    result = analyze(rows)
    if not result['points']:
        print(result['summary'])
        return result
    print(f"\n{'point':14s} {'dX mm':>7s} {'dY mm':>7s} {'XY mm':>7s} {'after offset':>12s} {'dZ mm':>7s}")
    for p in result['points']:
        print(f"{p['label']:14s} {p['dx'] * 1000:7.1f} {p['dy'] * 1000:7.1f} {p['xy'] * 1000:7.1f} "
              f"{p['residual'] * 1000:12.1f} {p['dz'] * 1000:7.1f}")
    ox, oy = result['mean_offset']
    print(f"\n{result['n']} points | mean XY error {result['mean_xy'] * 1000:.1f} mm | max {result['max_xy'] * 1000:.1f} mm"
          f" | common offset dX {ox * 1000:+.1f} mm, dY {oy * 1000:+.1f} mm"
          f" | max left after removing it {result['max_residual'] * 1000:.1f} mm")
    print(result['summary'])
    print('(dZ is not an error: the camera sees the top surface, the tip stays above it.)')
    return result


def read_rows(path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def ask_numbers(prompt, scale):
    while True:
        text = input(prompt).replace(',', ' ').split()
        try:
            values = [float(v) * scale for v in text]
            if len(values) == 3:
                return values
        except ValueError:
            pass
        print('  please type three numbers, e.g.  0.012 -0.341 -0.205')


def record(a):
    from fruit_server import RealSenseVision
    vision = RealSenseVision(a.calibration, a.serial, a.conf)
    scale = 0.001 if a.arm_units == 'mm' else 1.0
    out = Path(a.out)
    rows = read_rows(out) if out.exists() else []
    print(__doc__.split('\n\n')[1])
    try:
        while True:
            cmd = input(f'\n[{len(rows)} points] Enter = measure, r = report, q = quit: ').strip().lower()
            if cmd == 'q':
                break
            if cmd == 'r':
                report(rows)
                continue
            found = vision.snapshot()
            if not found:
                print('  nothing detected; check that the fruit is in view')
                continue
            for i, f in enumerate(found):
                print(f"  [{i}] {f['class_name']} {f['confidence']:.2f}  World {f['xyz_world']}")
            index = 0
            if len(found) > 1:
                choice = input('  which one (number)? ').strip()
                index = int(choice) if choice.isdigit() and int(choice) < len(found) else 0
            fruit = found[index]
            label = input('  label for this point (e.g. centre, front-left): ').strip() or f'p{len(rows) + 1}'
            arm = ask_numbers(f'  arm tip X Y Z in {a.arm_units}: ', scale)
            rows.append(dict(zip(FIELDS, [label, fruit['class_name'], *fruit['xyz_world'], *arm])))
            with open(out, 'w', encoding='utf-8', newline='') as f:  # saved after every point
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            print(f'  saved to {out}')
    finally:
        vision.close()
    report(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--calibration', help='JSON file containing T_world_camera')
    p.add_argument('--serial', help='head camera serial number')
    p.add_argument('--conf', type=float, default=0.5)
    p.add_argument('--out', default='refpoints.csv')
    p.add_argument('--arm-units', choices=('m', 'mm'), default='m', help='units of the positions you type')
    p.add_argument('--report', metavar='CSV', help='only print the table for a saved file')
    a = p.parse_args()
    if a.report:
        report(read_rows(a.report))
    elif not a.calibration:
        p.error('--calibration is required to record points')
    else:
        record(a)


if __name__ == '__main__':
    main()
