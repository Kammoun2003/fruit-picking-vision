"""A fake robot that answers like the robot's action API, for testing without the robot.

    python voice/mock_robot.py --objects apple=2,banana=1,battery=1 --delay 1

Listens on POST /action ({"method": ..., "parameters": {...}}), simulates a table and prints every
call. Reply formats follow the battery project's agent: grasp_object -> [success, error_code]
(1 = object not there, 2 = automatic mode), set_work_mode -> [success, mode], ...
Standard library only; nothing real moves.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


class MockRobot:
    def __init__(self, objects=None, mode='auto', delay=0.0):
        self.table = dict(objects or {})   # class -> count on the table
        self.mode, self.delay = mode, delay
        self.holding = None
        self.placed = []                    # (object, destination) in order
        self.calls = []                     # (method, parameters) in order
        self.lock = threading.Lock()

    def handle(self, method, params):
        """Return (http_status, reply) for one call."""
        with self.lock:
            self.calls.append((method, params))
        if method in ('grasp_object', 'move_object_to'):
            time.sleep(self.delay)          # motions take time
        with self.lock:
            names = [n for n, k in self.table.items() for _ in range(k)]
            if method == 'query_work_mode':
                return 200, {'result': self.mode}
            if method == 'set_work_mode':
                if params.get('mode') not in ('auto', 'manual'):
                    return 200, {'result': [False, self.mode]}
                self.mode = params['mode']
                return 200, {'result': [True, self.mode]}
            if method in ('start_work', 'suspend_work'):
                return 200, {'result': True}
            if method == 'detect_objects':
                return 200, {'result': {'object_name': names}}
            if method == 'check_object_exist':
                return 200, {'result': {n: self.table.get(n, 0) > 0 for n in params.get('object_name', [])}}
            if method == 'check_count':
                return 200, {'result': {n: k for n, k in self.table.items() if k}}
            if method == 'grasp_object':
                name = params.get('object_name')
                if self.mode == 'auto':
                    return 200, {'result': [False, 2]}
                if self.table.get(name, 0) <= 0 or self.holding:
                    return 200, {'result': [False, 1]}
                self.table[name] -= 1
                self.holding = name
                return 200, {'result': [True, 0]}
            if method == 'move_object_to':
                if self.holding != params.get('object_name') or not params.get('to'):
                    return 200, {'result': [False, 'not holding this object']}
                self.placed.append((self.holding, params['to']))
                self.holding = None
                return 200, {'result': [True, params['to']]}
            if method == 'return_to_home':
                return 200, {'result': True}
            return 404, {'error': 'unknown method ' + str(method)}


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
            if verbose:
                print(f'{time.strftime("%H:%M:%S")}  {method}({json.dumps(params, ensure_ascii=False)})'
                      f'  ->  {json.dumps(reply, ensure_ascii=False)}   table={robot.table}', flush=True)
            raw = json.dumps(reply, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def parse_objects(text):
    objects = {}
    for item in filter(None, text.split(',')):
        name, _, count = item.partition('=')
        objects[name.strip()] = int(count or 1)
    return objects


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--objects', default='apple=2,banana=1,pepper=1,potato=1,battery=1')
    p.add_argument('--mode', choices=('auto', 'manual'), default='auto')
    p.add_argument('--delay', type=float, default=1.0, help='seconds per grasp or move')
    p.add_argument('--port', type=int, default=5000)
    a = p.parse_args()
    robot = MockRobot(parse_objects(a.objects), a.mode, a.delay)
    server = make_server(robot, port=a.port)
    print(f'Mock robot on http://127.0.0.1:{a.port}/action  table={robot.table}  mode={robot.mode}  (Ctrl+C to quit)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
