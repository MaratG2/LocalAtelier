import contextlib
import io
import json
import re
import sqlite3
import time
import uuid
import threading
from pathlib import Path


def identifier():
    return uuid.uuid4().hex


def now():
    return time.time()


class Store:
    personal = False

    def read_file(self, name):
        return (self.assets / name).read_bytes()

    def open_media(self, name):
        return io.BytesIO(self.read_file(name)) if self.personal else self.assets / name

    def write_image(self, name, image, format='PNG', **options):
        buffer = io.BytesIO()
        image.save(buffer, format=format, **options)
        self.write_file(name, buffer.getvalue())

    def write_file(self, name, data):
        path = self.assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def file_exists(self, name):
        return (self.assets / name).is_file()

    def remove_asset_files(self, asset_id):
        """Delete only the files owned by this generated UUID, never references."""
        if not re.fullmatch(r'[0-9a-f]{32}', asset_id):
            raise ValueError('Invalid asset identifier')
        from .vault import remove_work_tree
        parent = self.assets.resolve()
        if not parent.is_relative_to(self.root) or self.assets.is_symlink():
            raise ValueError('Invalid asset directory')
        paths = [self.assets / name for name in
                 (asset_id + '.png', asset_id + '-thumb.png', asset_id + '.json', asset_id)]
        for path in paths:
            if path.is_symlink() or not path.resolve().is_relative_to(parent):
                raise ValueError('Invalid asset file path')
        for path in paths:
            if path.is_dir():
                remove_work_tree(path, parent)
            else:
                path.unlink(missing_ok=True)

    def input_path(self, name):
        return self.assets / name

    def output_folder(self, name):
        folder = self.assets / name
        folder.mkdir()
        return folder

    def seal_folder(self, name):
        """Persist a completed native output directory (ordinary stores already do)."""

    @contextlib.contextmanager
    def file_scope(self):
        yield

    def __init__(self, root, memory=False):
        self.root = Path(root).resolve()
        self.memory = memory
        self.db_lock = threading.RLock()
        self.database = f"file:atelier-{identifier()}?mode=memory&cache=shared" if memory else str(self.root / "atelier.sqlite3")
        self.anchor = sqlite3.connect(self.database, uri=memory, check_same_thread=False) if memory else None
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets = self.root / "assets"
        self.assets.mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT 'green', favorite INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    kind TEXT NOT NULL, filename TEXT NOT NULL, thumbnail TEXT NOT NULL,
                    name TEXT NOT NULL, prompt TEXT NOT NULL DEFAULT '', model_id TEXT,
                    width INTEGER NOT NULL, height INTEGER NOT NULL, seed INTEGER,
                    favorite INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), model_id TEXT NOT NULL,
                    status TEXT NOT NULL, phase TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL, completed INTEGER NOT NULL DEFAULT 0, request TEXT NOT NULL,
                    result_ids TEXT NOT NULL DEFAULT '[]', error TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, runtime_path TEXT NOT NULL,
                    verified REAL, verification TEXT, linked REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(projects)')}
            for name, definition in {'style_prompt': "TEXT NOT NULL DEFAULT ''", 'style_reference_id': 'TEXT', 'inherit_style': 'INTEGER NOT NULL DEFAULT 1'}.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE projects ADD COLUMN {name} {definition}')
            db.execute("INSERT OR IGNORE INTO projects(id,name,created,updated) VALUES('inbox','My creations',?,?)", (now(), now()))
            db.execute("UPDATE jobs SET status='interrupted', phase='Interrupted',error='The studio restarted before this job finished.', updated=? WHERE status IN ('queued','running')", (now(),))

    @contextlib.contextmanager
    def connect(self):
        if self.memory:
            self.db_lock.acquire()
        db = sqlite3.connect(self.database, timeout=30, uri=self.memory)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if self.memory:
            db.execute("PRAGMA temp_store=MEMORY")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
            if self.memory:
                self.db_lock.release()

    def all(self, sql, params=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self.connect() as db:
            db.execute(sql, params)

    def setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def project(self, project_id):
        return self.one("SELECT * FROM projects WHERE id=?", (project_id,))

    def projects(self, archived=False):
        return self.all('''SELECT p.*, (SELECT COUNT(*) FROM assets a WHERE a.project_id=p.id AND a.kind IN ('generated','mesh','video') AND a.deleted=0) AS asset_count,
            (SELECT id FROM assets a WHERE a.project_id=p.id AND a.kind IN ('generated','mesh','video') AND a.deleted=0 ORDER BY created DESC LIMIT 1) AS cover_id
            FROM projects p WHERE archived=? ORDER BY p.favorite DESC, p.updated DESC''', (int(archived),))

    def asset(self, asset_id):
        row = self.one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if row:
            row["metadata"] = json.loads(row["metadata"])
            row["url"] = f"/api/assets/{asset_id}/file"
            row["thumbnail_url"] = f"/api/assets/{asset_id}/thumbnail"
            if row["kind"] == "mesh" and row["metadata"].get("preview_updated"):
                row["thumbnail_url"] += f"?v={row['metadata']['preview_updated']}"
        return row

    def job(self, job_id):
        row = self.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row:
            row["result_ids"] = json.loads(row["result_ids"])
            row["request"] = json.loads(row["request"])
        return row

    def update_job(self, job_id, **values):
        values["updated"] = now()
        self.execute(f"UPDATE jobs SET {','.join(key+'=?' for key in values)} WHERE id=?", (*values.values(), job_id))
