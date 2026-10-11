"""Short-lived sessions: in-memory SQLite and an isolated, disposable scratch root.

This is application privacy, not secure erasure. Native GPU workers need files.
No temporary job, prompt or asset row is ever inserted in the durable database.
"""
import contextlib
import contextvars
import shutil
import threading
import time

from .storage import Store, identifier


class SessionStore(Store):
    def __init__(self, root, durable):
        super().__init__(root, memory=True)
        self.durable = durable
        self.closed = False
        self.touched = time.monotonic()
        for row in durable.all('SELECT * FROM projects'):
            self.execute(f"INSERT OR REPLACE INTO projects ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))

    def asset(self, asset_id):
        asset = super().asset(asset_id)
        if asset:
            asset['temporary'] = True
            return asset
        asset = self.durable.asset(asset_id)
        if asset:
            for key in ('filename', 'thumbnail'):
                asset[key] = str(self.durable.assets / asset[key])
        return asset


class SessionRouter:
    def __init__(self, durable):
        self.durable = durable
        self.context = contextvars.ContextVar('atelier_session', default=None)
        self.sessions = {}
        self.lock = threading.RLock()
        self.folder = durable.root / 'temporary'
        self.folder.mkdir(exist_ok=True)
        self.cleanup_error = None
        self.pending_cleanup = set()
        # Only our marked session folders; never follow a directory link.
        for folder in self.folder.iterdir():
            if folder.is_dir() and not folder.is_symlink() and (folder / '.atelier-temporary').is_file():
                self._remove(folder)

    @property
    def current(self):
        key = self.context.get()
        if key is None:
            return self.durable
        if key not in self.sessions:
            raise ValueError('Temporary session ended. Reload the studio.')
        return self.sessions[key]

    @property
    def temporary(self):
        return self.current is not self.durable

    def __getattr__(self, name):
        if name in {'setting', 'set_setting'}:
            return getattr(self.durable, name)
        return getattr(self.current, name)

    def all(self, sql, params=()):
        if ' FROM models' in sql:
            return self.durable.all(sql, params)
        # Model deletion, GPU release, archiving and reference protection must
        # include every session, even though history is scoped to one session.
        if 'FROM jobs' in sql and "'queued','running'" in sql:
            with self.lock:
                rows = [row for db in [self.durable, *self.sessions.values()] for row in db.all(sql, params)]
            if 'COUNT(*)' in sql:
                return [{'count': sum(row['count'] for row in rows)}]
            return rows
        return self.current.all(sql, params)

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    @contextlib.contextmanager
    def use(self, session):
        token = self.context.set(session)
        try:
            yield
        finally:
            self.context.reset(token)

    def begin(self):
        with self.lock:
            if len(self.sessions) >= 8:
                raise ValueError('Too many temporary sessions. Close an existing session first.')
            key = identifier()
            session = SessionStore(self.folder / key, self.durable)
            (session.root / '.atelier-temporary').touch()
            self.sessions[key] = session
            return key

    def _remove(self, folder):
        if folder.resolve().parent != self.folder.resolve() or folder.is_symlink():
            raise ValueError('Invalid temporary directory')
        try:
            shutil.rmtree(folder)
        except OSError:
            self.pending_cleanup.add(folder)
            self.cleanup_error = 'Temporary file cleanup is pending. Close the studio workers and restart to retry.'
            return False
        self.pending_cleanup.discard(folder)
        if not self.pending_cleanup:
            self.cleanup_error = None
        return True

    def close(self, key, queue):
        with self.lock:
            session = self.sessions.get(key)
            if not session:
                return
            session.closed = True
            with self.use(key):
                for row in session.all("SELECT id FROM jobs WHERE status IN ('queued','running')"):
                    queue.cancel(row['id'])
            self.reap()

    def reap(self):
        with self.lock:
            for key, session in list(self.sessions.items()):
                if session.closed and not session.one("SELECT id FROM jobs WHERE status IN ('queued','running')"):
                    # The queue may still be releasing a worker after marking done.
                    if getattr(session, 'working', False):
                        continue
                    if self._remove(session.root):
                        session.anchor.close()
                        del self.sessions[key]

    def expire(self, queue):
        while True:
            time.sleep(15)
            with self.lock:
                keys = [key for key, s in self.sessions.items() if time.monotonic() - s.touched > 900]
            for key in keys:
                self.close(key, queue)
            self.reap()
