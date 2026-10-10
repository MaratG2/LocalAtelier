import contextlib
import json
import sqlite3
import time
import uuid
from pathlib import Path


def identifier():
    return uuid.uuid4().hex


def now():
    return time.time()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
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
            db.execute("INSERT OR IGNORE INTO projects(id,name,created,updated) VALUES('inbox','My creations',?,?)", (now(), now()))
            db.execute("UPDATE jobs SET status='interrupted', phase='Interrupted',error='The studio restarted before this job finished.', updated=? WHERE status IN ('queued','running')", (now(),))

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "atelier.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

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
        return self.all('''SELECT p.*, (SELECT COUNT(*) FROM assets a WHERE a.project_id=p.id AND a.kind IN ('generated','mesh') AND a.deleted=0) AS asset_count,
            (SELECT id FROM assets a WHERE a.project_id=p.id AND a.kind IN ('generated','mesh') AND a.deleted=0 ORDER BY created DESC LIMIT 1) AS cover_id
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
