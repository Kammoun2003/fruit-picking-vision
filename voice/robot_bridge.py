"""Run validated voice commands on the robot's action API, step by step. Standard library only.

The robot does not understand "PICK apple". It offers small methods on one route,
POST <base>/action with {"method": ..., "parameters": {...}} (grasp_object, move_object_to, ...).
This module turns each command into a sequence of those calls, checks every reply before the
next call, and stops between steps when STOP is pressed.

    bridge = RobotBridge(RobotClient('http://127.0.0.1:5000'), load_places('robot_places.json'))
    bridge.start('PICK', 'apple')      # motions run in the background
    bridge.status()                    # progress of the running task
    bridge.query('COUNT', 'apple')     # queries return at once
    bridge.stop()                      # cancel between steps + suspend_work on the robot

An accepted call is not proof that the object physically arrived; messages say "requested".
The robot's software stop finishes the current motion first; it does not replace the emergency stop.
"""
import json
from pathlib import Path
import threading
import time
from urllib import error, request

from intent import CLASSES, INTRUDERS, MOTIONS, OBJECTS

QUERIES = frozenset({'STATUS', 'COUNT'})
QUERY_TIMEOUT_S = 10    # status, detection, mode changes, stop
MOTION_TIMEOUT_S = 120  # a grasp or a move can take a while


class RobotError(Exception):
    """A robot call failed or was refused. The message is short and safe to show."""


class Cancelled(Exception):
    """STOP was pressed; the remaining steps are not sent."""


def load_places(path):
    """Destination name (the `to` of move_object_to) for every class, plus the hand-over place.
    null or a missing entry = not set up yet: commands that need it are refused with a clear message."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    places = {k: data.get(k) for k in CLASSES + ('hand_over',)}
    invalid = [k for k, v in places.items() if v is not None and (not isinstance(v, str) or not v.strip())]
    if invalid:
        raise ValueError('robot places file: invalid destination for ' + ', '.join(invalid))
    return places


class RobotClient:
    def __init__(self, base_url, path='/action'):
        self.url = base_url.rstrip('/') + path

    def call(self, method, timeout=QUERY_TIMEOUT_S, **parameters):
        """One POST; returns the reply as a dict or raises RobotError. Never retried automatically."""
        body = json.dumps({'method': method, 'parameters': parameters}, ensure_ascii=False).encode('utf-8')
        req = request.Request(self.url, data=body, headers={'Content-Type': 'application/json'})
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read(1_000_001)
        except error.HTTPError as exc:
            raise RobotError(f'{method}: robot answered HTTP {exc.code}') from None
        except (error.URLError, OSError):
            raise RobotError(f'{method}: robot not reachable or no answer within {timeout} s') from None
        try:
            value = json.loads(raw) if len(raw) <= 1_000_000 else None
        except ValueError:
            value = None
        if not isinstance(value, dict):
            raise RobotError(f'{method}: robot reply is not a JSON object')
        return value


def _result(reply, method):
    if 'result' not in reply:
        raise RobotError(f'{method}: robot reply has no result')
    return reply['result']


def _pair(reply, method):
    """Replies like [success, detail] (grasp_object, set_work_mode)."""
    value = _result(reply, method)
    if not isinstance(value, list) or len(value) != 2 or type(value[0]) is not bool:
        raise RobotError(f'{method}: unexpected reply {value!r}')
    return value


class RobotBridge:
    def __init__(self, client, places, max_sort=10):
        self.client, self.places, self.max_sort = client, places, max_sort
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self._task = None

    # ---------- public API ----------
    def start(self, command, obj=None):
        """Start a motion command in the background; refuses while another task runs."""
        self._check(command, obj, MOTIONS)
        needed = {'PICK': 'hand_over', 'SORT': obj, 'REMOVE': obj}.get(command)
        if needed and not self.places.get(needed):
            what = 'the hand-over place' if needed == 'hand_over' else f'the {needed}'
            raise RobotError(f'no destination set up yet for {what}')
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RobotError('a task is still running; wait for it or press Stop')
            self._cancel.clear()
            self._task = dict(command=command, object=obj, state='running', steps=[], message='started',
                              started=time.time(), finished=None)
            self._thread = threading.Thread(target=self._run, args=(command, obj), daemon=True)
            self._thread.start()
        return dict(message=f'Task started: {command}' + (f' {obj}' if obj else ''), task=self.status())

    def query(self, command, obj=None):
        """STATUS or COUNT; answers at once and never moves the robot."""
        self._check(command, obj, QUERIES)
        if command == 'STATUS':
            mode = _result(self.client.call('query_work_mode'), 'query_work_mode')
            task = self.status()
            text = f'Robot mode: {mode}.'
            if task:
                text += f" Last task {task['command']}{' ' + task['object'] if task['object'] else ''}: " \
                        f"{task['state']} ({task['message']})."
            return dict(message=text, mode=mode, task=task)
        names = self._detect(self.client.call)
        if obj:
            n = names.count(obj)
            return dict(message=f'{n} {obj} detected.', count=n)
        counts = {c: names.count(c) for c in CLASSES if c in names}
        text = ', '.join(f'{n} {c}' for c, n in counts.items()) or 'nothing'
        return dict(message=f'Detected: {text}.', counts=counts)

    def stop(self):
        """Cancel the running task between steps, then ask the robot to suspend its work."""
        self._cancel.set()
        reply = self.client.call('suspend_work')
        ok = _result(reply, 'suspend_work') is True
        text = 'Stop sent: the robot finishes the current motion, then stops.' if ok else \
               'Stop sent, but the robot did not confirm it; use the emergency stop if needed.'
        return dict(message=text, confirmed=ok, task=self.status())

    def status(self):
        with self._lock:
            return None if self._task is None else dict(self._task, steps=list(self._task['steps']))

    def wait(self, timeout=None):
        """Wait until the current task has finished (used by tests and scripts)."""
        thread = self._thread
        if thread:
            thread.join(timeout)
        return self.status()

    # ---------- task execution ----------
    def _check(self, command, obj, allowed):
        if command not in allowed or obj not in OBJECTS.get(command, (None,)):
            raise ValueError(f'not allowed here: {command} {obj}')

    def _run(self, command, obj):
        try:
            message = getattr(self, '_plan_' + command.lower())(obj)
            state = 'done'
        except Cancelled:
            state, message = 'cancelled', 'stopped by STOP before the next step'
        except RobotError as exc:
            state, message = 'failed', str(exc)
        except Exception as exc:  # never leave the task in "running"
            state, message = 'failed', f'internal error: {type(exc).__name__}'
        with self._lock:
            self._task.update(state=state, message=message, finished=time.time())

    def _step(self, method, timeout=QUERY_TIMEOUT_S, **parameters):
        """One robot call inside a task: cancelled before sending if STOP was pressed."""
        if self._cancel.is_set():
            raise Cancelled
        label = method + '(' + ', '.join(f'{k}={v}' for k, v in parameters.items()) + ')'
        with self._lock:
            self._task['steps'].append(label)
            self._task['message'] = f"step {len(self._task['steps'])}: {label}"
        return self.client.call(method, timeout=timeout, **parameters)

    def _detect(self, call):
        result = _result(call('detect_objects'), 'detect_objects')
        names = result.get('object_name') if isinstance(result, dict) else None
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise RobotError(f'detect_objects: unexpected reply {result!r}')
        return names

    def _manual(self):
        ok, _ = _pair(self._step('set_work_mode', mode='manual'), 'set_work_mode')
        if not ok:
            raise RobotError('could not switch the robot to manual mode')

    def _exists(self, name):
        result = _result(self._step('check_object_exist', object_name=[name]), 'check_object_exist')
        if not isinstance(result, dict) or type(result.get(name)) is not bool:
            raise RobotError(f'check_object_exist: unexpected reply {result!r}')
        return result[name]

    def _grasp(self, name):
        ok, code = _pair(self._step('grasp_object', MOTION_TIMEOUT_S, object_name=name), 'grasp_object')
        if not ok:
            reasons = {1: f'no {name} found on the table', 2: 'grasping is not allowed in automatic mode',
                       3: f'the {name} is outside the reachable work area', 4: 'the robot is already holding an object',
                       5: f'the arm motion failed while grasping the {name}'}
            raise RobotError(reasons.get(code, f'grasping the {name} failed (code {code})'))

    def _move(self, name, place):
        result = self._step('move_object_to', MOTION_TIMEOUT_S, object_name=name, to=place).get('result', True)
        if result is False or (isinstance(result, list) and result and result[0] is False):
            raise RobotError(f'moving the {name} to {place} failed')

    def _pick_and_place(self, name, place):
        self._grasp(name)
        self._move(name, place)

    # ---------- one plan per motion command ----------
    def _plan_pick(self, obj):
        self._manual()
        self._pick_and_place(obj, self.places['hand_over'])
        return f'{obj} brought to {self.places["hand_over"]} (requested; not visually verified)'

    def _plan_remove(self, obj):
        self._manual()
        self._pick_and_place(obj, self.places[obj])
        return f'{obj} moved to {self.places[obj]} (requested; not visually verified)'

    def _plan_sort(self, obj):
        self._manual()
        for done in range(self.max_sort):
            if not self._exists(obj):
                return f'{done} {obj} sorted into {self.places[obj]}; none left'
            self._pick_and_place(obj, self.places[obj])
        return f'{self.max_sort} {obj} sorted; stopped at the limit of {self.max_sort} per command'

    def _plan_start_single(self, obj):
        self._manual()
        names = self._detect(self._step)
        if not names:
            raise RobotError('nothing detected on the table')
        names = [n for n in names if self.places.get(n)]
        if not names:
            raise RobotError('nothing on the table has a destination set up yet')
        # Intruders first, so a battery never stays among the food.
        name = next((n for n in names if n in INTRUDERS), names[0])
        self._pick_and_place(name, self.places[name])
        return f'{name} moved to {self.places[name]} (requested; not visually verified)'

    def _plan_start_auto(self, obj):
        ok, _ = _pair(self._step('set_work_mode', mode='auto'), 'set_work_mode')
        if not ok:
            raise RobotError('could not switch the robot to automatic mode')
        if _result(self._step('start_work'), 'start_work') is not True:
            raise RobotError('the robot did not start automatic sorting')
        return 'automatic sorting started by the robot'
