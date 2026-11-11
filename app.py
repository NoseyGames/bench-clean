"""Bench Clean: authenticated loopback-only Windows dashboard."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
import webbrowser

import psutil
import system
from storage import Scanner


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.scanner = Scanner()
        self.apps = []
        self.warnings = []
        self.apps_status = 'loading'
        self.metrics = dict(processes=[], cpu=0, memory={}, status='warming up')
        self.gpu = {}
        self.gpu_time = 0
        self.gpu_error = 'Waiting for GPU counters.'
        self.job = dict(status='idle')
        self.refresh_lock = threading.Lock()

    def refresh(self):
        if not self.refresh_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                self.apps_status = 'loading'
            apps, warnings = system.inventory()
            with self.lock:
                self.apps, self.warnings, self.apps_status = apps, warnings, 'ready'
        except Exception as exc:
            with self.lock:
                self.apps_status, self.warnings = 'failed', [str(exc)]
        finally:
            self.refresh_lock.release()

    def gpu_loop(self):
        while not self.stop.is_set():
            try:
                data = system.gpu_sample()
                with self.lock:
                    self.gpu, self.gpu_time, self.gpu_error = data, time.time(), None
            except Exception as exc:
                with self.lock:
                    self.gpu, self.gpu_error = {}, str(exc)
            self.stop.wait(4)

    def monitor(self):
        previous = {}
        matched_paths, inventory_version = {}, None
        psutil.cpu_percent()
        while not self.stop.wait(2):
            now = time.monotonic()
            current, rows = {}, []
            with self.lock:
                if inventory_version != id(self.apps):
                    matched_paths.clear()
                    inventory_version = id(self.apps)
                apps, gpu = list(self.apps), dict(self.gpu)
                gpu_ok = self.gpu_error is None and time.time() - self.gpu_time < 20
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'memory_info', 'cpu_times', 'create_time'], ad_value=None):
                p = proc.info
                if not p['pid'] or p['cpu_times'] is None:
                    continue
                key = (p['pid'], p['create_time'])
                seconds = p['cpu_times'].user + p['cpu_times'].system
                current[key] = (now, seconds)
                old = previous.get(key)
                cpu = max(0, min(100, (seconds - old[1]) / (now - old[0]) * 100 / (psutil.cpu_count() or 1))) if old else None
                executable = p['exe']
                if executable not in matched_paths:
                    matched_paths[executable] = system.match_app(executable, apps)
                rows.append(dict(pid=p['pid'], name=p['name'] or 'Unknown', cpu=cpu,
                                 ram=p['memory_info'].rss if p['memory_info'] else None,
                                 gpu=gpu.get(p['pid'], 0) if gpu_ok else None,
                                 app=matched_paths[executable]))
            previous = current
            mem = psutil.virtual_memory()
            with self.lock:
                self.metrics = dict(processes=rows, cpu=psutil.cpu_percent(),
                                    memory=dict(total=mem.total, used=mem.total-mem.available, percent=mem.percent),
                                    status='live', sampled=time.time(), gpu_error=self.gpu_error,
                                    gpu_sampled=self.gpu_time)

    def start_remove(self, ids):
        with self.lock:
            if self.job['status'] == 'running':
                raise ValueError('An uninstall job is already running.')
            if not isinstance(ids, list) or not ids or len(ids) > 40 or any(not isinstance(x, str) for x in ids):
                raise ValueError('Select between 1 and 40 installed apps.')
            selected = []
            for item in dict.fromkeys(ids):
                app = next((a for a in self.apps if a['id'] == item), None)
                if not app or not app['removable']:
                    raise ValueError('App missing or protected. Refresh apps.')
                selected.append(dict(app))
            self.job = dict(status='running', results=[])
        def run():
            for app in selected:
                try:
                    message, success = system.remove_app(app), True
                except Exception as exc:
                    message, success = str(exc), False
                logging.info('Uninstall %s: %s', app['name'], message)
                with self.lock:
                    self.job['results'].append(dict(name=app['name'], success=success, message=message))
            self.refresh()
            with self.lock:
                self.job['status'] = 'complete'
        threading.Thread(target=run, daemon=True).start()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port, state):
        super().__init__(('127.0.0.1', port), Handler)
        self.state = state
        self.token = secrets.token_urlsafe(32)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # Never log the browser's session secret.

    def reply(self, status, data, mime='application/json'):
        body = json.dumps(data, ensure_ascii=True).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self, api=False):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self.reply(403, {'error': 'Invalid host.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            self.reply(403, {'error': 'Invalid origin.'})
            return False
        if api and not hmac.compare_digest(self.headers.get('X-Bench-Token', ''), self.server.token):
            self.reply(401, {'error': 'Reopen the dashboard using the URL printed by the launcher.'})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.authorized(path.startswith('/api/')):
            return
        state = self.server.state
        if path == '/api/state':
            with state.lock:
                data = dict(apps=[{k: v for k, v in a.items() if not k.startswith('_')} for a in state.apps],
                            apps_status=state.apps_status, warnings=list(state.warnings),
                            metrics=dict(state.metrics), job=json.loads(json.dumps(state.job)))
            data.update(storage=state.scanner.snapshot(), drives=system.drives())
            self.reply(200, data)
        elif path in ('/', '/app.js', '/style.css'):
            filename, mime = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
            self.reply(200, (system.ROOT / 'web' / filename).read_bytes(), mime)
        else:
            self.reply(404, {'error': 'Not found.'})

    def do_POST(self):
        if not self.authorized(True):
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 16384 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Expected a small JSON request.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
            state = self.server.state
            path = urlsplit(self.path).path
            if path == '/api/uninstall':
                if body.get('confirmed') is not True:
                    raise ValueError('Explicit confirmation is required.')
                state.start_remove(body.get('ids'))
            elif path == '/api/refresh':
                threading.Thread(target=state.refresh, daemon=True).start()
            elif path == '/api/scan':
                raw = body.get('path', '')
                if not isinstance(raw, str) or not raw or raw.startswith(('\\\\', '//')):
                    raise ValueError('Choose a local directory, not a network or device path.')
                root = Path(raw)
                if not root.is_absolute() or not root.is_dir() or root.is_symlink() or root.is_junction():
                    raise ValueError('Choose an existing local directory (not a link or junction).')
                state.scanner.start(root.resolve())
            elif path == '/api/cancel-scan':
                state.scanner.cancel.set()
            elif path == '/api/settings':
                os.startfile('ms-settings:appsfeatures')
            elif path == '/api/shutdown':
                with state.lock:
                    if state.job['status'] == 'running':
                        raise ValueError('Wait for the uninstall job before stopping.')
                state.stop.set()
                state.scanner.cancel.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.reply(404, {'error': 'Not found.'})
                return
            self.reply(200, {'ok': True})
        except (ValueError, TypeError, OSError) as exc:
            self.reply(400, {'error': str(exc)})


def main():
    if os.name != 'nt':
        raise SystemExit('Bench Clean requires Windows 10 or 11.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0, help='Default: automatically choose a free loopback port')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    log_dir = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BenchClean'
    log_dir.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(log_dir / 'actions.log',
                        maxBytes=1_000_000, backupCount=2, encoding='utf-8')], format='%(asctime)s %(message)s')
    state = State()
    server = Server(args.port, state)
    workers = [threading.Thread(target=target, daemon=True) for target in (state.refresh, state.monitor, state.gpu_loop)]
    for worker in workers:
        worker.start()
    url = f'{server.origin}/#{server.token}'
    print('Bench Clean | local Windows utility\nKeep this window open. Ctrl+C stops the server.\n' + url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        state.stop.set()
        state.scanner.cancel.set()
        server.server_close()
        for worker in workers:
            worker.join(timeout=1)


if __name__ == '__main__':
    main()
