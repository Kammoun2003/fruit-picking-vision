"""Tests: voice/robot_bridge.py against fruit_server.py over HTTP, with a fake camera and fake motion
modules. Nothing moves.

    python robot/test_fruit_server.py
"""
import copy
from pathlib import Path
import sys
import tempfile
import textwrap
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'voice'))
from fruit_server import DryRunMotion, FruitRobot, ModuleMotion, load_config, make_server  # noqa: E402
from robot_bridge import RobotBridge, RobotClient, RobotError, load_places  # noqa: E402

CONFIG = load_config(HERE / 'fruit_server_config.json')
PLACES = load_places(HERE.parent / 'voice' / 'robot_places.json')


def fruit(name, conf, xyz):
    return {'class_name': name, 'confidence': conf, 'xyz_world': list(xyz)}


# Positions measured on the real table (2026-11-16), plus a battery and a banana outside the work area.
TABLE = [fruit('apple', 0.96, (-0.0748, -0.3793, -0.3055)), fruit('apple', 0.95, (0.0873, -0.5364, -0.3058)),
         fruit('pepper', 0.96, (-0.2041, -0.5448, -0.2935)), fruit('pepper', 0.95, (0.103, -0.3509, -0.2859)),
         fruit('battery', 0.94, (0.0, -0.45, -0.29)), fruit('banana', 0.50, (0.50, -0.40, -0.30))]


class FakeVision:
    def __init__(self, fruits):
        self.fruits = fruits

    def snapshot(self):
        return copy.deepcopy(self.fruits)


def write_module(folder, name, body):
    path = Path(folder) / f'{name}.py'
    path.write_text(textwrap.dedent(body), encoding='utf-8')
    return path


class ServerTest(unittest.TestCase):
    """The bridge against the server in dry-run."""

    def setUp(self):
        self.motion = DryRunMotion(verbose=False)
        self.robot = FruitRobot(FakeVision(TABLE), self.motion, copy.deepcopy(CONFIG))
        self.server = make_server(self.robot, port=0, verbose=False)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = RobotClient(f'http://127.0.0.1:{self.server.server_port}')
        self.bridge = RobotBridge(self.client, PLACES)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def run_task(self, command, obj=None):
        self.bridge.start(command, obj)
        return self.bridge.wait(10)

    def test_pick_apple_plans_a_safe_grasp(self):
        task = self.run_task('PICK', 'apple')
        self.assertEqual(task['state'], 'done', task)
        # most confident apple: 10 cm above, open, down to 2 cm below the top surface, close, up, hand-over
        self.assertEqual(self.motion.log, ['above [-0.0748, -0.3793, -0.2055]', 'hand open',
                                           'down [-0.0748, -0.3793, -0.3255]', 'hand close',
                                           'up [-0.0748, -0.3793, -0.2055]', 'place hand_over', 'hand open'])

    def test_sort_apples_until_none_left(self):
        task = self.run_task('SORT', 'apple')
        self.assertEqual(task['state'], 'done', task)
        self.assertIn('2 apple sorted', task['message'])

    def test_remove_battery_to_waste_bin(self):
        task = self.run_task('REMOVE', 'battery')
        self.assertEqual(task['state'], 'done', task)
        self.assertIn('place waste_bin', self.motion.log)

    def test_count_and_status(self):
        self.assertEqual(self.bridge.query('COUNT', 'apple')['count'], 2)
        self.assertEqual(self.bridge.query('COUNT')['counts']['pepper'], 2)
        self.assertIn('manual', self.bridge.query('STATUS')['message'])

    def test_outside_work_area_refused(self):
        task = self.run_task('PICK', 'banana')
        self.assertEqual(task['state'], 'failed')
        self.assertIn('code 3', task['message'])
        self.assertEqual(self.motion.log, [])

    def test_missing_object(self):
        self.robot.vision = FakeVision([])
        self.assertIn('no potato', self.run_task('PICK', 'potato')['message'])

    def test_unknown_place_refused(self):
        self.client.call('grasp_object', object_name='apple')
        reply = self.client.call('move_object_to', object_name='apple', to='kitchen')
        self.assertEqual(reply['result'], [False, 'unknown place kitchen'])

    def test_start_auto_battery_first_then_stops_at_unreachable(self):
        self.assertEqual(self.run_task('START_AUTO')['state'], 'done')
        for _ in range(100):
            if self.client.call('query_work_mode')['result'] == 'manual':
                break
            time.sleep(0.05)
        places = [e for e in self.motion.log if e.startswith('place ')]
        self.assertEqual(places[0], 'place waste_bin')  # intruder first
        self.assertEqual(len(places), 5)                # 2 apples, 2 peppers, battery; banana out of reach

    def test_grasp_refused_in_auto_mode(self):
        self.client.call('set_work_mode', mode='auto')
        self.assertEqual(self.client.call('grasp_object', object_name='apple')['result'], [False, 2])

    def test_unknown_method(self):
        with self.assertRaises(RobotError):
            self.client.call('fly_away')


class ModuleMotionTest(unittest.TestCase):
    """A motion module file like fruit_motion.py: pick_at / place_at / home returning bool."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        # a helper next to the module, like position_manager.py next to fruit_motion.py
        write_module(self.folder, 'helper_positions', 'def load(name):\n    return [0.0] * 6\n')

    def robot(self, module_path):
        return FruitRobot(FakeVision(TABLE), ModuleMotion(module_path), copy.deepcopy(CONFIG))

    def test_working_module_gets_world_coordinates_and_place_names(self):
        path = write_module(self.folder, 'good_motion', '''
            from helper_positions import load
            CALLS = []
            def pick_at(x, y, z):
                CALLS.append(('pick_at', x, y, z)); return True
            def place_at(name):
                CALLS.append(('place_at', name, load(name))); return True
            def home():
                CALLS.append(('home',)); return True
        ''')
        robot = self.robot(path)
        self.assertEqual(robot.grasp('apple'), [True, 0])
        self.assertEqual(robot.place('apple', 'hand_over'), [True, 'hand_over'])
        self.assertEqual(robot.handle('return_to_home', {}), (200, {'result': True}))
        calls = robot.motion.module.CALLS
        self.assertEqual(calls[0], ('pick_at', -0.0748, -0.3793, -0.3055))
        self.assertEqual(calls[1], ('place_at', 'hand_over', [0.0] * 6))
        self.assertEqual(calls[2], ('home',))

    def test_draft_returning_false_is_a_failed_motion(self):
        path = write_module(self.folder, 'draft_motion', '''
            def pick_at(x, y, z):
                print('[DRY-RUN] pick plan'); return False
            def place_at(name):
                return False
            def home():
                return False
        ''')
        robot = self.robot(path)
        self.assertEqual(robot.grasp('apple'), [False, 5])
        self.assertIsNone(robot.holding)

    def test_exception_or_non_bool_is_a_failed_motion(self):
        path = write_module(self.folder, 'bad_motion', '''
            def pick_at(x, y, z):
                raise RuntimeError('arm error 7')
            def place_at(name):
                return 'ok'
            def home():
                return 1
        ''')
        robot = self.robot(path)
        self.assertEqual(robot.grasp('apple'), [False, 5])
        robot.holding = 'apple'
        self.assertEqual(robot.place('apple', 'hand_over'), [False, 'motion failed'])
        self.assertEqual(robot.handle('return_to_home', {})[1], {'result': False})

    def test_module_without_required_functions_is_rejected(self):
        path = write_module(self.folder, 'incomplete_motion', 'def pick_at(x, y, z):\n    return True\n')
        with self.assertRaises(ValueError):
            ModuleMotion(path)

    def test_outside_work_area_never_reaches_the_module(self):
        path = write_module(self.folder, 'strict_motion', '''
            CALLS = []
            def pick_at(x, y, z):
                CALLS.append((x, y, z)); return True
            def place_at(name):
                return True
            def home():
                return True
        ''')
        robot = self.robot(path)
        self.assertEqual(robot.grasp('banana'), [False, 3])
        self.assertEqual(robot.motion.module.CALLS, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
