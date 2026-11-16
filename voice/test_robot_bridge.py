"""Tests for robot_bridge.py against the mock robot over real HTTP. No robot needed.

    python voice/test_robot_bridge.py
"""
import json
from pathlib import Path
import sys
import tempfile
import time
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_robot import MockRobot, make_server  # noqa: E402
from robot_bridge import RobotBridge, RobotClient, RobotError, load_places  # noqa: E402

PLACES = load_places(Path(__file__).resolve().parent / 'robot_places.json')


class BridgeTest(unittest.TestCase):
    def setUp(self, objects=None, delay=0.0, max_sort=10):
        self.robot = MockRobot(objects if objects is not None else
                               {'apple': 2, 'banana': 1, 'battery': 1}, mode='auto', delay=delay)
        self.server = make_server(self.robot, port=0, verbose=False)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.bridge = RobotBridge(RobotClient(f'http://127.0.0.1:{self.server.server_port}'), PLACES, max_sort)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def restart(self, **kwargs):
        self.tearDown()
        self.setUp(**kwargs)

    def methods(self):
        return [m for m, _ in self.robot.calls]

    def run_task(self, command, obj=None):
        self.bridge.start(command, obj)
        return self.bridge.wait(10)

    # ---------- motion plans ----------
    def test_pick(self):
        task = self.run_task('PICK', 'apple')
        self.assertEqual(task['state'], 'done', task)
        self.assertEqual(self.methods(), ['set_work_mode', 'grasp_object', 'move_object_to'])
        self.assertEqual(self.robot.calls[0][1], {'mode': 'manual'})
        self.assertEqual(self.robot.placed, [('apple', 'hand_over')])
        self.assertEqual(self.robot.table['apple'], 1)

    def test_pick_missing_object_stops_before_move(self):
        task = self.run_task('PICK', 'pepper')
        self.assertEqual(task['state'], 'failed')
        self.assertIn('no pepper', task['message'])
        self.assertNotIn('move_object_to', self.methods())

    def test_remove_battery_goes_to_waste_bin(self):
        task = self.run_task('REMOVE', 'battery')
        self.assertEqual(task['state'], 'done', task)
        self.assertEqual(self.robot.placed, [('battery', 'waste_bin')])

    def test_sort_until_none_left(self):
        task = self.run_task('SORT', 'apple')
        self.assertEqual(task['state'], 'done', task)
        self.assertEqual(self.robot.placed, [('apple', 'box_apple')] * 2)
        self.assertIn('2 apple sorted', task['message'])

    def test_sort_stops_at_limit(self):
        self.restart(objects={'potato': 5}, max_sort=2)
        task = self.run_task('SORT', 'potato')
        self.assertEqual(len(self.robot.placed), 2)
        self.assertIn('limit', task['message'])

    def test_start_single_takes_intruder_first(self):
        task = self.run_task('START_SINGLE')
        self.assertEqual(task['state'], 'done', task)
        self.assertEqual(self.robot.placed, [('battery', 'waste_bin')])

    def test_start_single_on_empty_table(self):
        self.restart(objects={})
        task = self.run_task('START_SINGLE')
        self.assertEqual(task['state'], 'failed')
        self.assertIn('nothing detected', task['message'])

    def test_start_auto(self):
        task = self.run_task('START_AUTO')
        self.assertEqual(task['state'], 'done', task)
        self.assertEqual(self.methods(), ['set_work_mode', 'start_work'])
        self.assertEqual(self.robot.mode, 'auto')

    # ---------- queries ----------
    def test_count_one_class(self):
        self.assertEqual(self.bridge.query('COUNT', 'apple')['count'], 2)

    def test_count_all(self):
        self.assertEqual(self.bridge.query('COUNT')['counts'], {'banana': 1, 'apple': 2, 'battery': 1})

    def test_status(self):
        self.assertIn('auto', self.bridge.query('STATUS')['message'])
        self.run_task('PICK', 'apple')
        self.assertIn('PICK apple: done', self.bridge.query('STATUS')['message'])

    # ---------- stop and concurrency ----------
    def test_stop_cancels_between_steps(self):
        self.restart(objects={'apple': 5}, delay=0.3)
        self.bridge.start('SORT', 'apple')
        time.sleep(0.5)                      # inside the first grasp or move
        answer = self.bridge.stop()
        task = self.bridge.wait(10)
        self.assertTrue(answer['confirmed'])
        self.assertEqual(task['state'], 'cancelled')
        self.assertIn('suspend_work', self.methods())
        self.assertLess(len(self.robot.placed), 5)

    def test_second_task_refused_while_running(self):
        self.restart(objects={'apple': 3}, delay=0.3)
        self.bridge.start('SORT', 'apple')
        with self.assertRaises(RobotError):
            self.bridge.start('PICK', 'apple')
        self.bridge.stop()
        self.bridge.wait(10)

    # ---------- refused inputs and robot errors ----------
    def test_invalid_combinations_refused(self):
        for command, obj in [('PICK', 'battery'), ('REMOVE', 'apple'), ('SORT', None), ('STATUS', None),
                             ('COUNT', 'orange'), ('FLY', None)]:
            with self.assertRaises(ValueError, msg=f'{command} {obj}'):
                (self.bridge.query if command in ('COUNT',) else self.bridge.start)(command, obj)
        self.assertEqual(self.robot.calls, [])

    def test_robot_not_reachable(self):
        bridge = RobotBridge(RobotClient('http://127.0.0.1:1'), PLACES)
        with self.assertRaises(RobotError) as ctx:
            bridge.query('STATUS')
        self.assertIn('not reachable', str(ctx.exception))

    def test_unknown_method_is_an_error(self):
        with self.assertRaises(RobotError) as ctx:
            self.bridge.client.call('fly_away')
        self.assertIn('HTTP 404', str(ctx.exception))

    def test_places_file_must_be_complete(self):
        path = Path(tempfile.mkdtemp()) / 'places.json'
        path.write_text(json.dumps({'banana': 'box_1'}))
        with self.assertRaises(ValueError):
            load_places(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
