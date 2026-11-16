"""Tests: voice/robot_bridge.py against fruit_server.py over HTTP, with a fake camera. Nothing moves.

    python robot/test_fruit_server.py
"""
import copy
from pathlib import Path
import sys
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'voice'))
from fruit_server import DryRunMotion, FruitRobot, RealMotion, load_config, make_server  # noqa: E402
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


class FakeArm:
    def __init__(self, log):
        self.log = log

    def Movej(self, pose):
        self.log.append(('movej', pose))
        return 0

    def Movel(self, pose):
        self.log.append(('movel', pose))
        return 0

    def move_to_idle_position(self):
        self.log.append(('home',))


class FakeHand:
    def __init__(self, log):
        self.log = log

    def move_prepare_grasp_status(self):
        self.log.append(('open',))

    def move_grasp_battery_status(self):
        self.log.append(('close',))


class ServerTest(unittest.TestCase):
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
        log = self.motion.log
        # highest-confidence apple; approach 10 cm above, grasp 2 cm below the top surface, lift, hand-over
        self.assertTrue(log[0].startswith('movej [-0.0748, -0.3793, -0.2055'), log[0])
        self.assertEqual(log[1], 'hand "prepare/open"')
        self.assertTrue(log[2].startswith('movel [-0.0748, -0.3793, -0.3255'), log[2])
        self.assertEqual(log[3], 'hand "grasp/close"')
        self.assertIn('hand_over', log[5])
        self.assertEqual(log[6], 'hand "prepare/open"')

    def test_sort_apples_until_none_left(self):
        task = self.run_task('SORT', 'apple')
        self.assertEqual(task['state'], 'done', task)
        self.assertIn('2 apple sorted', task['message'])

    def test_remove_battery_to_waste_bin(self):
        task = self.run_task('REMOVE', 'battery')
        self.assertEqual(task['state'], 'done', task)
        self.assertIn('waste_bin', self.motion.log[5])

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
        task = self.run_task('PICK', 'potato')
        self.assertIn('no potato', task['message'])

    def test_start_auto_battery_first_then_stops_at_unreachable(self):
        task = self.run_task('START_AUTO')
        self.assertEqual(task['state'], 'done', task)
        for _ in range(100):
            if self.client.call('query_work_mode')['result'] == 'manual':
                break
            time.sleep(0.05)
        places = [e for e in self.motion.log if e.startswith('movej "<pose of')]
        self.assertIn('waste_bin', places[0])          # intruder first
        self.assertEqual(len(places), 5)               # 2 apples, 2 peppers, battery; banana out of reach

    def test_grasp_refused_in_auto_mode(self):
        self.client.call('set_work_mode', mode='auto')
        self.assertEqual(self.client.call('grasp_object', object_name='apple')['result'], [False, 2])

    def test_unknown_method(self):
        with self.assertRaises(RobotError):
            self.client.call('fly_away')


class RealMotionTest(unittest.TestCase):
    def test_real_mode_needs_taught_orientation_and_places(self):
        log = []
        robot = FruitRobot(FakeVision(TABLE), RealMotion(FakeArm(log), FakeHand(log)), copy.deepcopy(CONFIG))
        self.assertEqual(robot.grasp('apple'), [False, 6])
        robot.cfg['grasp_orientation'] = [3.14, 0.0, 0.0]
        self.assertEqual(robot.grasp('apple'), [True, 0])
        self.assertEqual(robot.place('apple', 'hand_over'), [False, 'place hand_over not taught yet'])
        robot.cfg['places']['hand_over'] = [0.3, -0.2, 0.1, 3.14, 0.0, 0.0]
        self.assertEqual(robot.place('apple', 'hand_over'), [True, 'hand_over'])
        self.assertEqual([e[0] for e in log], ['movej', 'open', 'movel', 'close', 'movel', 'movej', 'open'])

    def test_failed_motion_is_reported(self):
        log = []
        arm = FakeArm(log)
        arm.Movel = lambda pose: -1
        cfg = copy.deepcopy(CONFIG)
        cfg['grasp_orientation'] = [3.14, 0.0, 0.0]
        robot = FruitRobot(FakeVision(TABLE), RealMotion(arm, FakeHand(log)), cfg)
        self.assertEqual(robot.grasp('apple'), [False, 5])
        self.assertIsNone(robot.holding)


if __name__ == '__main__':
    unittest.main(verbosity=2)
