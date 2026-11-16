"""Fruit robot server: the battery demo's /action methods, backed by the fruit detector and World XYZ.

    python fruit_server.py --calibration <result.json> --serial <head camera serial>          # dry-run
    python fruit_server.py --calibration <result.json> --serial <head camera serial> --real   # arm moves

POST /action with {"method": ..., "parameters": {...}}, same methods and reply formats as the battery
demo's server, so voice/robot_bridge.py works unchanged:

    detect_objects, check_object_exist, get_target_position, check_count     (camera only)
    grasp_object, move_object_to, return_to_home                             (motion)
    set_work_mode, query_work_mode, start_work, suspend_work                 (modes, automatic sorting)

Dry-run (default): nothing moves; every planned pose is printed and returned. A grasped object is
hidden from later detections (3 cm radius) so that SORT and START_AUTO terminate as they would for real.

Grasp: approach above the fruit -> open the hand -> straight down -> close -> straight up. The fruit
position is the top surface from fruit_localizer (World frame); the target height is that surface plus
`grasp_offset_m` (negative = lower). Positions outside the configured work area are refused.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
for folder in (HERE, HERE.parent / 'detector'):
    sys.path.insert(0, str(folder))

GRASP_ERRORS = {1: 'object not detected', 2: 'not allowed in automatic mode', 3: 'outside the work area',
                4: 'already holding an object', 5: 'motion failed', 6: 'grasp pose not configured'}


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ('workspace', 'places', 'approach_height_m', 'grasp_offset_m', 'lift_height_m'):
        if key not in cfg:
            raise ValueError(f'config: missing {key}')
    for axis in 'xyz':
        lo, hi = cfg['workspace'][axis]
        if not lo < hi:
            raise ValueError(f'config: workspace {axis} must be [min, max]')
    for name, pose in cfg['places'].items():
        if pose is not None and (not isinstance(pose, list) or len(pose) != 6):
            raise ValueError(f'config: place {name} must be null or [x, y, z, rx, ry, rz]')
    orientation = cfg.get('grasp_orientation')
    if orientation is not None and len(orientation) != 3:
        raise ValueError('config: grasp_orientation must be null or [rx, ry, rz]')
    return cfg


# ---------------------------------------------------------------- vision
class RealSenseVision:
    """Head camera + fruit_localizer; each snapshot uses a fresh aligned frame."""

    def __init__(self, calibration, serial=None, conf=0.5):
        import numpy as np
        import pyrealsense2 as rs
        from fruit_localizer import FruitLocalizer, load_transform
        self.np, self.rs = np, rs
        self.localizer = FruitLocalizer(load_transform(calibration), conf=conf)
        self.pipeline, config = rs.pipeline(), rs.config()
        if serial:
            config.enable_device(serial)
        config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 15)
        config.enable_stream(rs.stream.depth, 1280, 720, rs.format.z16, 15)
        profile = self.pipeline.start(config)
        self.scale = profile.get_device().first_depth_sensor().get_depth_scale()
        self.align = rs.align(rs.stream.color)
        self.lock = threading.Lock()
        for _ in range(15):  # let auto-exposure settle
            self.pipeline.wait_for_frames()

    def snapshot(self):
        with self.lock:
            for _ in range(3):  # drop buffered frames: the scene may have changed
                self.pipeline.poll_for_frames()
            frames = self.align.process(self.pipeline.wait_for_frames())
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            image = self.np.asanyarray(color.get_data())
            depth_m = self.np.asanyarray(depth.get_data()).astype(self.np.float32) * self.scale
            return self.localizer.locate(image, depth_m, color.profile.as_video_stream_profile().intrinsics)

    def close(self):
        self.pipeline.stop()


# ---------------------------------------------------------------- motion
class DryRunMotion:
    """Prints and records every planned action; nothing moves."""
    dry_run = True

    def __init__(self, verbose=True):
        self.log, self.verbose = [], verbose

    def _do(self, action, *values):
        entry = action + ' ' + ' '.join(json.dumps(v) for v in values)
        self.log.append(entry)
        if self.verbose:
            print('  [dry-run]', entry, flush=True)
        return True

    def move_joint_space(self, pose):
        return self._do('movej', pose)

    def move_linear(self, pose):
        return self._do('movel', pose)

    def open_hand(self):
        return self._do('hand', 'prepare/open')

    def close_hand(self):
        return self._do('hand', 'grasp/close')

    def home(self):
        return self._do('home')


class RealMotion:
    """Drives one arm through the lab's grasp_demo classes (arm_controller.GraspArm style):
    Movej / Movel return 0 on success; the hand has prepare and grasp postures."""
    dry_run = False

    def __init__(self, arm, hand):
        self.arm, self.hand = arm, hand

    def move_joint_space(self, pose):
        return self.arm.Movej(list(pose)) == 0

    def move_linear(self, pose):
        return self.arm.Movel(list(pose)) == 0

    def open_hand(self):
        self.hand.move_prepare_grasp_status()
        return True

    def close_hand(self):
        self.hand.move_grasp_battery_status()
        return True

    def home(self):
        self.arm.move_to_idle_position()
        return True


def make_real_motion(cfg):
    """Connect the arm and hand like the battery demo does. To be completed on the robot with the
    lab's connection code (robot SDK object, IP, which arm); kept out of this file on purpose."""
    raise NotImplementedError('Real motion is not connected yet: create the arm and hand objects here '
                              '(see grasp_demo/scripts/ohandtest*.py) together with the robot team.')


# ---------------------------------------------------------------- server logic
class FruitRobot:
    def __init__(self, vision, motion, cfg):
        self.vision, self.motion, self.cfg = vision, motion, cfg
        self.mode = 'manual'
        self.holding = None
        self.virtually_removed = []   # dry-run only: positions of objects "picked" so far
        self.motion_lock = threading.Lock()
        self.suspend = threading.Event()
        self.auto_thread = None

    # ---------- detection helpers
    def detections(self):
        found = self.vision.snapshot()
        if self.motion.dry_run:
            found = [f for f in found
                     if all(math.dist(f['xyz_world'], p) > 0.03 for p in self.virtually_removed)]
        return found

    def best(self, name):
        candidates = [f for f in self.detections() if f['class_name'] == name]
        return max(candidates, key=lambda f: f['confidence']) if candidates else None

    def in_workspace(self, xyz):
        return all(lo <= v <= hi for v, (lo, hi) in zip(xyz, (self.cfg['workspace'][a] for a in 'xyz')))

    # ---------- motions
    def _pose(self, x, y, z):
        # Dry-run may run before the grasp orientation is taught; zeros only show the planned position.
        orientation = self.cfg.get('grasp_orientation') or [0.0, 0.0, 0.0]
        return [round(x, 4), round(y, 4), round(z, 4)] + list(orientation)

    def grasp(self, name):
        if self.mode == 'auto' and threading.current_thread() is not self.auto_thread:
            return [False, 2]
        if self.holding:
            return [False, 4]
        target = self.best(name)
        if target is None:
            return [False, 1]
        x, y, z = target['xyz_world']
        if not self.in_workspace((x, y, z)):
            return [False, 3]
        if self.cfg.get('grasp_orientation') is None and not self.motion.dry_run:
            return [False, 6]
        above = self._pose(x, y, z + self.cfg['approach_height_m'])
        at = self._pose(x, y, z + self.cfg['grasp_offset_m'])
        lifted = self._pose(x, y, z + self.cfg['lift_height_m'])
        with self.motion_lock:
            ok = (self.motion.move_joint_space(above) and self.motion.open_hand()
                  and self.motion.move_linear(at) and self.motion.close_hand() and self.motion.move_linear(lifted))
        if not ok:
            return [False, 5]
        self.holding = name
        if self.motion.dry_run:
            self.virtually_removed.append(target['xyz_world'])
        return [True, 0]

    def place(self, name, to):
        if self.holding != name:
            return [False, f'not holding {name}']
        if to not in self.cfg['places']:
            return [False, f'unknown place {to}']
        pose = self.cfg['places'][to]
        if pose is None:
            if not self.motion.dry_run:
                return [False, f'place {to} not taught yet']
            pose = f'<pose of {to}, not taught yet>'
        with self.motion_lock:
            ok = self.motion.move_joint_space(pose) and self.motion.open_hand()
        if not ok:
            return [False, 'motion failed']
        self.holding = None
        return [True, to]

    def destination(self, name):
        return self.cfg.get('class_places', {}).get(name)

    # ---------- automatic mode: everything into its place, intruders first
    def _auto_loop(self):
        while not self.suspend.is_set() and self.mode == 'auto':
            found = [f for f in self.detections() if self.destination(f['class_name'])]
            if not found:
                break
            found.sort(key=lambda f: (f['class_name'] != 'battery', -f['confidence']))
            name = found[0]['class_name']
            if self.grasp(name)[0] is not True or self.place(name, self.destination(name))[0] is not True:
                break
        self.mode = 'manual'

    # ---------- the /action dispatcher
    def handle(self, method, p):
        if method == 'detect_objects':
            return 200, {'result': {'object_name': [f['class_name'] for f in self.detections()]}}
        if method == 'check_object_exist':
            names = {f['class_name'] for f in self.detections()}
            return 200, {'result': {n: n in names for n in p.get('object_name', [])}}
        if method == 'check_count':
            counts = {}
            for f in self.detections():
                counts[f['class_name']] = counts.get(f['class_name'], 0) + 1
            return 200, {'result': counts}
        if method == 'get_target_position':
            target = self.best(p.get('object_name'))
            if target is None:
                return 200, {'result': {}}
            return 200, {'result': dict(zip('xyz', target['xyz_world']))}
        if method == 'query_work_mode':
            return 200, {'result': self.mode}
        if method == 'set_work_mode':
            if p.get('mode') not in ('auto', 'manual'):
                return 200, {'result': [False, self.mode]}
            if p['mode'] == 'manual':
                self.suspend.set()
            self.mode = p['mode']
            return 200, {'result': [True, self.mode]}
        if method == 'start_work':
            if self.mode != 'auto' or (self.auto_thread and self.auto_thread.is_alive()):
                return 200, {'result': False}
            self.suspend.clear()
            self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
            self.auto_thread.start()
            return 200, {'result': True}
        if method == 'suspend_work':
            self.suspend.set()
            return 200, {'result': True}
        if method == 'grasp_object':
            return 200, {'result': self.grasp(p.get('object_name'))}
        if method == 'move_object_to':
            return 200, {'result': self.place(p.get('object_name'), p.get('to'))}
        if method == 'return_to_home':
            with self.motion_lock:
                ok = self.motion.home()
            self.virtually_removed.clear()
            return 200, {'result': bool(ok)}
        return 404, {'error': f'unknown method {method}'}


def make_server(robot, host='127.0.0.1', port=5000, verbose=True):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                if self.path != '/action':
                    raise ValueError('use POST /action')
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                method, params = body['method'], body.get('parameters') or {}
                status, reply = robot.handle(method, params)
            except (ValueError, KeyError, TypeError) as exc:
                method, params, status, reply = '?', {}, 400, {'error': str(exc)}
            except Exception as exc:  # camera or arm error: answer instead of hanging
                method, params, status, reply = method, params, 500, {'error': f'{type(exc).__name__}: {exc}'}
            if verbose:
                print(f'{time.strftime("%H:%M:%S")}  {method}({json.dumps(params, ensure_ascii=False)})'
                      f'  ->  {json.dumps(reply, ensure_ascii=False)}', flush=True)
            raw = json.dumps(reply, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--calibration', required=True, help='JSON file containing T_world_camera')
    p.add_argument('--config', default=str(HERE / 'fruit_server_config.json'))
    p.add_argument('--serial', help='head camera serial number')
    p.add_argument('--conf', type=float, default=0.5, help='minimum detection confidence for actions')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=5000)
    p.add_argument('--real', action='store_true', help='move the real arm (default: dry-run)')
    a = p.parse_args()

    cfg = load_config(a.config)
    motion = make_real_motion(cfg) if a.real else DryRunMotion()
    vision = RealSenseVision(a.calibration, a.serial, a.conf)
    robot = FruitRobot(vision, motion, cfg)
    server = make_server(robot, a.host, a.port)
    print(f'Fruit server on http://{a.host}:{a.port}/action  mode={"REAL ARM" if a.real else "dry-run (nothing moves)"}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        vision.close()


if __name__ == '__main__':
    main()
