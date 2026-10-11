"""Idle-aware shutdown and update monitoring for the local Windows launcher."""

import json
import os
import threading
import time
from pathlib import Path


RESTART_EXIT = 75


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    temp.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temp, path)


def source_stamp(root):
    """Watch application source only: never weights, assets, prompts or logs."""
    root = Path(root)
    files = [root / 'run.py', *sorted((root / 'atelier').rglob('*.py'))]
    result = []
    for path in files:
        try:
            stat = path.stat()
            result.append((str(path.relative_to(root)), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            pass
    return tuple(result)


def idle_reason(app):
    store, jobs, models = (app.extensions[key] for key in ('store', 'jobs', 'models'))
    if jobs.queue.unfinished_tasks or store.one("SELECT id FROM jobs WHERE status IN ('queued','running') LIMIT 1"):
        return 'Waiting for generation to finish'
    if any(op['status'] == 'running' for op in models.operations.values()):
        return 'Waiting for model operations to finish'
    if store.sessions:
        return 'Waiting for incognito sessions to end; download temporary results first'
    return None


class ManagedLifecycle:
    def __init__(self, app, root, folder, identity):
        self.app, self.root, self.folder, self.identity = app, Path(root), Path(folder), identity
        self.exit_code = 0
        self.loaded_stamp = source_stamp(root)
        self.observed_stamp = self.loaded_stamp
        self.changed_at = time.monotonic()
        self.pending = None
        self.request_id = None
        self.last_state = None
        app.config['LAUNCHER'] = {'managed': True, 'instance_id': identity['instance_id']}

    def report(self, state, reason=None):
        value = {**self.identity, 'server_pid': os.getpid(), 'state': state,
                 'reason': reason, 'request_id': self.request_id}
        if value != self.last_state:
            write_json(self.folder / 'state.json', value)
            self.last_state = value

    def poll(self, server):
        command = read_json(self.folder / 'command.json')
        if command.get('session_id') == self.identity['session_id'] and command.get('action') in {'restart', 'stop'}:
            if command.get('id') != self.request_id:
                self.request_id = command['id']
                self.pending = command['action']
        stamp = source_stamp(self.root)
        if stamp != self.observed_stamp:
            self.observed_stamp, self.changed_at = stamp, time.monotonic()
        if stamp != self.loaded_stamp and time.monotonic() - self.changed_at >= 3:
            self.pending = self.pending or 'restart'
        if not self.pending:
            self.report('running')
            return False
        jobs, models, store = (self.app.extensions[key] for key in ('jobs', 'models', 'store'))
        # The queue/model locks also guard new submissions. Once idle, freeze
        # admission before stopping HTTP so a late request cannot strand a job.
        with models.lock, jobs.lock, store.lock:
            reason = idle_reason(self.app)
            if reason:
                self.report('waiting', reason)
                return False
            jobs.accepting = models.accepting = False
            self.app.config['STUDIO_STOPPING'] = True
            self.exit_code = RESTART_EXIT if self.pending == 'restart' else 0
            self.report('restarting' if self.exit_code else 'stopping')
        server.shutdown()
        return True

    def watch(self, server):
        self.report('running')
        while True:
            time.sleep(1)
            try:
                if self.poll(server):
                    return
            except Exception as error:
                # An editor's partial save or transient file lock must not kill
                # an active studio. Report the problem and retry next second.
                self.report('monitor-error', str(error))


class InstanceLock:
    """Kernel-owned lock; automatically released on exit, including crashes."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        if not self.path.stat().st_size:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise RuntimeError('The launcher is already running') from None
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()
