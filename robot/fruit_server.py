"""Fruit robot server: the battery demo's /action methods, backed by the fruit detector and World XYZ.

    python fruit_server.py --calibration <result.json> --serial <head camera serial>
    python fruit_server.py --calibration <result.json> --serial <serial> --motion-module <path>/fruit_motion.py

POST /action with {"method": ..., "parameters": {...}}, same methods and reply formats as the battery
demo's server, so voice/robot_bridge.py works unchanged:

    detect_objects, check_object_exist, get_target_position, check_count     (camera only)
    grasp_object, move_object_to, return_to_home                             (motion)
    set_work_mode, query_work_mode, start_work, suspend_work                 (modes, automatic sorting)

The server decides WHAT to do (which object, where it is, whether it is inside the work area, modes,
stopping); a motion module decides HOW the arm moves. A motion module provides three functions that
block until the motion has finished:

    pick_at(x, y, z) -> bool    World frame, metres; z is the top surface of the object
    place_at(name)   -> bool    one of the place names in the config
    home()           -> bool

Without --motion-module the built-in dry-run is used: nothing moves, the planned steps are printed, and
a picked object is hidden from later detections (3 cm radius) so SORT and START_AUTO finish as for real.
"""
import argparse
import importlib.util
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

# grasp_object replies [false, code]
NOT_DETECTED, AUTO_MODE, OUTSIDE_AREA, HOLDING, MOTION_FAILED = 1, 2, 3, 4, 5


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ('workspace', 'places', 'class_places'):
        if key not in cfg:
            raise ValueError(f'config: missing {key}')
    for axis in 'xyz':
        lo, hi = cfg['workspace'][axis]
        if not lo < hi:
            raise ValueError(f'config: workspace {axis} must be [min, max]')
    unknown = [p for p in cfg['class_places'].values() if p not in cfg['places']]
    if unknown:
        raise ValueError('config: class_places uses unknown places ' + ', '.join(unknown))
    return cfg


# ---------------------------------------------------------------- vision
class RealSenseVision:
    """Head camera + fruit_localizer; each snapshot uses a fresh aligned frame."""

    def __init__(self, calibration, serial=None, conf=0.5):
        import numpy as np
        import pyrealsense2 as rs
        from fruit_localizer import FruitLocalizer, load_transform
        self.np = np
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
    """Prints and records the planned steps; nothing moves. Heights only shape the printout."""
    dry_run = True

    def __init__(self, approach_height=0.10, grasp_offset=-0.02, verbose=True):
        self.approach, self.offset, self.verbose = approach_height, grasp_offset, verbose
        self.log = []

    def _do(self, *steps):
        for step in steps:
            self.log.append(step)
            if self.verbose:
                print('  [dry-run]', step, flush=True)
        return True

    def pick_at(self, x, y, z):
        r = lambda v: round(v, 4)
        return self._do(f'above {[r(x), r(y), r(z + self.approach)]}', 'hand open', f'down {[r(x), r(y), r(z + self.offset)]}',
                        'hand close', f'up {[r(x), r(y), r(z + self.approach)]}')

    def place_at(self, name):
        return self._do(f'place {name}', 'hand open')

    def home(self):
        return self._do('home')


class ModuleMotion:
    """Calls pick_at / place_at / home of a motion module file (e.g. fruit_motion.py on the robot).
    Anything other than True, including an exception, counts as a failed motion."""
    dry_run = False

    def __init__(self, path):
        path = Path(path).resolve()
        sys.path.insert(0, str(path.parent))  # the module's own imports (position manager, adapters)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        missing = [f for f in ('pick_at', 'place_at', 'home') if not callable(getattr(self.module, f, None))]
        if missing:
            raise ValueError(f'{path.name} has no ' + ', '.join(missing))

    def _call(self, name, *args):
        try:
            return getattr(self.module, name)(*args) is True
        except Exception as exc:
            print(f'  [motion] {name}{args} raised {type(exc).__name__}: {exc}', flush=True)
            return False

    def pick_at(self, x, y, z):
        return self._call('pick_at', float(x), float(y), float(z))

    def place_at(self, name):
        return self._call('place_at', name)

    def home(self):
        return self._call('home')


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
    def grasp(self, name):
        if self.mode == 'auto' and threading.current_thread() is not self.auto_thread:
            return [False, AUTO_MODE]
        if self.holding:
            return [False, HOLDING]
        target = self.best(name)
        if target is None:
            return [False, NOT_DETECTED]
        if not self.in_workspace(target['xyz_world']):
            return [False, OUTSIDE_AREA]
        with self.motion_lock:
            ok = self.motion.pick_at(*target['xyz_world'])
        if not ok:
            return [False, MOTION_FAILED]
        self.holding = name
        if self.motion.dry_run:
            self.virtually_removed.append(target['xyz_world'])
        return [True, 0]

    def place(self, name, to):
        if self.holding != name:
            return [False, f'not holding {name}']
        if to not in self.cfg['places']:
            return [False, f'unknown place {to}']
        with self.motion_lock:
            ok = self.motion.place_at(to)
        if not ok:
            return [False, 'motion failed']
        self.holding = None
        return [True, to]

    # ---------- automatic mode: everything into its place, intruders first
    def _auto_loop(self):
        while not self.suspend.is_set() and self.mode == 'auto':
            found = [f for f in self.detections() if f['class_name'] in self.cfg['class_places']]
            if not found:
                break
            found.sort(key=lambda f: (f['class_name'] != 'battery', -f['confidence']))
            name = found[0]['class_name']
            if self.grasp(name)[0] is not True or self.place(name, self.cfg['class_places'][name])[0] is not True:
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
            return 200, {'result': dict(zip('xyz', target['xyz_world'])) if target else {}}
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
            method, params = '?', {}
            try:
                if self.path != '/action':
                    raise ValueError('use POST /action')
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                method, params = body['method'], body.get('parameters') or {}
                status, reply = robot.handle(method, params)
            except (ValueError, KeyError, TypeError) as exc:
                status, reply = 400, {'error': str(exc)}
            except Exception as exc:  # camera error: answer instead of hanging
                status, reply = 500, {'error': f'{type(exc).__name__}: {exc}'}
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
    p.add_argument('--motion-module', help='fruit_motion.py with pick_at/place_at/home (default: dry-run)')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=5000)
    a = p.parse_args()

    cfg = load_config(a.config)
    motion = ModuleMotion(a.motion_module) if a.motion_module else DryRunMotion()
    vision = RealSenseVision(a.calibration, a.serial, a.conf)
    robot = FruitRobot(vision, motion, cfg)
    server = make_server(robot, a.host, a.port)
    mode = f'motion module {a.motion_module}' if a.motion_module else 'dry-run (nothing moves)'
    print(f'Fruit server on http://{a.host}:{a.port}/action  -  {mode}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        vision.close()


if __name__ == '__main__':
    main()
