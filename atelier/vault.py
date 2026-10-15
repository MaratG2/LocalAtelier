"""Password-wrapped data key, authenticated blobs and an encrypted SQLite snapshot.

No password, unwrapped key, SQL journal or metadata index is persisted. Native
tools can require plaintext scratch files; these are scoped, never the archive.
This is not secure erasure or protection against a compromised unlocked host.
"""
import contextlib
import contextvars
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from werkzeug.exceptions import TooManyRequests

from .storage import Store, identifier

MAGIC = b'ATVAULT1'
IDLE_SECONDS = 900


def remove_work_tree(path, parent):
    """Only owned scratch trees; tolerate Windows worker/antivirus handle lag."""
    path, parent = Path(path), Path(parent).resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(parent) or path.resolve() == parent:
        raise ValueError('Invalid temporary directory')
    def readonly_retry(function, filename, error):
        if not isinstance(error, PermissionError):
            raise error
        import stat
        os.chmod(filename, stat.S_IWRITE)
        function(filename)
    for delay in (0, .15, .4, 1.0):
        if delay:
            time.sleep(delay)
        try:
            if path.exists():
                shutil.rmtree(path, onexc=readonly_retry)
            return
        except PermissionError:
            if delay == 1.0:
                raise


def atomic_write(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.' + identifier() + '.tmp')
    try:
        with temp.open('xb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def password_key(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError('Use a password or passphrase with 12–1,024 characters.')
    # OWASP's scrypt minimum: N=2^17, r=8, p=1 (128 MiB).
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode('utf-8'))


def wrap_key(password, key):
    salt, nonce = os.urandom(16), os.urandom(12)
    wrapped = AESGCM(password_key(password, salt)).encrypt(nonce, key, b'atelier-vault-key-v1')
    return json.dumps(dict(version=1, salt=salt.hex(), nonce=nonce.hex(), wrapped=wrapped.hex())).encode()


class VaultStore(Store):
    personal = True

    def __init__(self, root, archive, key):
        Path(root).mkdir(parents=True, exist_ok=True)
        (Path(root) / '.atelier-temporary').touch()
        self.archive, self.key = Path(archive), key
        self.blobs = self.archive / 'blobs'
        self.blobs.mkdir(exist_ok=True)
        self.ready = False
        self.closed = False
        self.working = False
        self.readers = 0
        self.touched = time.monotonic()
        self.scopes = contextvars.ContextVar('vault_files', default=None)
        self.initial = self.read_encrypted(self.archive / 'catalog.bin', 'catalog') if (self.archive / 'catalog.bin').exists() else None
        super().__init__(root, memory=True)
        self.execute('CREATE TABLE IF NOT EXISTS vault_files (name TEXT PRIMARY KEY)')
        self.ready = True
        self.persist()

    @contextlib.contextmanager
    def connect(self):
        with self.db_lock:
            db = self.anchor
            if self.initial is not None:
                db.deserialize(self.initial)
                self.initial = None
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA temp_store=MEMORY')
            before = db.total_changes
            try:
                yield db
                db.commit()
                if self.ready and db.total_changes != before:
                    self.persist()
            except Exception:
                db.rollback()
                raise

    def persist(self):
        self.encrypt_stream(io.BytesIO(self.anchor.serialize()), self.archive / 'catalog.bin', 'catalog')

    def encrypt_stream(self, source, target, name):
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(self.key), modes.GCM(nonce)).encryptor()
        cipher.authenticate_additional_data(('atelier-v1:' + name).encode())
        temp = target.with_name(target.name + '.' + identifier() + '.tmp')
        try:
            with temp.open('xb') as output:
                output.write(MAGIC + nonce)
                while chunk := source.read(1024 * 1024):
                    output.write(cipher.update(chunk))
                output.write(cipher.finalize())
                output.write(cipher.tag)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def decrypt_stream(self, path, name, output):
        # Callers may use the plaintext only AFTER the authentication tag passes.
        try:
            with path.open('rb') as source:
                if source.read(8) != MAGIC:
                    raise ValueError('Personal-space data is damaged. Restore a backup.')
                nonce = source.read(12)
                source.seek(-16, 2)
                length = source.tell() - 20
                tag = source.read(16)
                source.seek(20)
                decryptor = Cipher(algorithms.AES(self.key), modes.GCM(nonce, tag)).decryptor()
                decryptor.authenticate_additional_data(('atelier-v1:' + name).encode())
                while length > 0:
                    chunk = source.read(min(1024 * 1024, length))
                    if not chunk:
                        raise InvalidTag()
                    output.write(decryptor.update(chunk))
                    length -= len(chunk)
                output.write(decryptor.finalize())
        except (InvalidTag, ValueError) as error:
            raise ValueError('Personal-space data is damaged. Restore a backup.') from error

    def read_encrypted(self, path, name):
        output = io.BytesIO()
        self.decrypt_stream(path, name, output)
        return output.getvalue()

    def normalized(self, name):
        name = str(name).replace('\\', '/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or ':' in name or not path.parts:
            raise ValueError('Invalid personal-space file path')
        return str(path)

    def blob(self, name):
        return self.blobs / (hmac.new(self.key, b'file:' + name.encode(), hashlib.sha256).hexdigest() + '.bin')

    def read_file(self, name):
        name = self.normalized(name)
        return self.read_encrypted(self.blob(name), name)

    def asset(self, asset_id):
        asset = super().asset(asset_id)
        if asset:
            asset['personal'] = True
        return asset

    def write_file(self, name, data):
        self.save_stream(name, io.BytesIO(data))

    def save_stream(self, name, source):
        name = self.normalized(name)
        with self.db_lock:
            self.encrypt_stream(source, self.blob(name), name)
            self.execute('INSERT OR IGNORE INTO vault_files VALUES(?)', (name,))

    def file_exists(self, name):
        return self.blob(self.normalized(name)).is_file()

    def remove_asset_files(self, asset_id):
        if not re.fullmatch(r'[0-9a-f]{32}', asset_id):
            raise ValueError('Invalid asset identifier')
        exact = {asset_id + '.png', asset_id + '-thumb.png', asset_id + '.json'}
        with self.connect() as db:
            names = [row['name'] for row in db.execute('SELECT name FROM vault_files')
                     if row['name'] in exact or row['name'].startswith(asset_id + '/')]
            for name in names:
                self.blob(name).unlink(missing_ok=True)
            db.executemany('DELETE FROM vault_files WHERE name=?', [(name,) for name in names])
        super().remove_asset_files(asset_id)

    def seal_folder(self, name):
        name = self.normalized(name)
        folder = self.assets / name
        for file in folder.rglob('*'):
            if file.is_symlink():
                raise ValueError('Linked files cannot be saved in personal space')
            if file.is_file():
                with file.open('rb') as source:
                    self.save_stream(file.relative_to(self.assets).as_posix(), source)
        remove_work_tree(folder, self.root)

    def output_folder(self, name):
        stack = self.scopes.get()
        if stack is None:
            raise RuntimeError('Personal files require a scoped operation')
        folder = super().output_folder(name)
        stack.callback(remove_work_tree, folder, self.root)
        return folder

    @contextlib.contextmanager
    def file_scope(self):
        stack = contextlib.ExitStack()
        token = self.scopes.set(stack)
        try:
            with stack:
                yield
        finally:
            self.scopes.reset(token)

    def input_path(self, name):
        name = self.normalized(name)
        stack = self.scopes.get()
        if stack is None:
            raise RuntimeError('Personal files require a scoped operation')
        folder = self.root / 'inputs' / identifier()
        folder.mkdir(parents=True)
        stack.callback(remove_work_tree, folder, self.root)
        # Video preview continuation needs its authenticated sidecar tensors too.
        prefix = str(PurePosixPath(name).with_suffix('.artifacts')) + '/'
        names = [name] + [r['name'] for r in self.all('SELECT name FROM vault_files') if r['name'].startswith(prefix)]
        for item in names:
            target = folder / item
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as output:
                self.decrypt_stream(self.blob(item), item, output)
        return folder / name

    def clear_work(self):
        for name in ('runtime',):
            path = self.root / name
            if path.exists():
                remove_work_tree(path, self.root)


class Vault:
    def __init__(self, router):
        self.router = router
        self.folder = router.durable.root / 'personal'
        self.folder.mkdir(exist_ok=True)
        self.config = self.folder / 'key.json'
        self.failures, self.retry_at = 0, 0

    @property
    def configured(self):
        return self.config.is_file()

    def unwrap(self, password):
        if time.monotonic() < self.retry_at:
            raise TooManyRequests('Too many password attempts. Wait a minute and try again.')
        try:
            row = json.loads(self.config.read_text())
            if row['version'] != 1:
                raise ValueError('Unsupported personal-space format')
            result = AESGCM(password_key(password, bytes.fromhex(row['salt']))).decrypt(
                bytes.fromhex(row['nonce']), bytes.fromhex(row['wrapped']), b'atelier-vault-key-v1')
            self.failures = 0
            return result
        except (InvalidTag, ValueError):
            self.failures += 1
            if self.failures >= 5:
                self.retry_at = time.monotonic() + 60
            raise ValueError('Incorrect password. Your personal space is still locked.') from None
        except (KeyError, TypeError, OSError):
            raise ValueError('Personal-space data is damaged. Restore a backup.') from None

    def setup(self, password):
        with self.router.lock:
            if self.configured:
                raise ValueError('A personal-space password is already set.')
            key = os.urandom(32)
            wrapped = wrap_key(password, key)
            # Initialize the encrypted catalog before exposing a configured vault.
            session = VaultStore(self.router.folder / identifier(), self.folder, key)
            session.anchor.close()
            self.router._remove(session.root)
            atomic_write(self.config, wrapped)

    def unlock(self, password):
        with self.router.lock:
            if not self.configured:
                raise ValueError('Set a personal-space password first.')
            key = self.unwrap(password)
            if any(s.personal for s in self.router.sessions.values()):
                raise ValueError('Personal space is already open or finishing a job. Lock it there first, then try again.')
            token = identifier() + identifier()
            try:
                session = VaultStore(self.router.folder / token, self.folder, key)
            except Exception:
                self.router._remove(self.router.folder / token)
                raise
            (session.root / '.atelier-temporary').touch()
            self.router.sessions[token] = session
            return token

    def change_password(self, current, new):
        with self.router.lock:
            key = self.unwrap(current)
            atomic_write(self.config, wrap_key(new, key))
