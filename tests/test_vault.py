import io
import json
import time
import unittest
import wave
from unittest.mock import patch

from PIL import Image

from atelier.app import create_app
from atelier.generation import save_image
import test_studio as studio_fixture
from test_studio import FakeRuntime
from test_meshes import fixture_glb


class VaultTests(unittest.TestCase):
    setUp = studio_fixture.StudioTests.setUp
    tearDown = studio_fixture.StudioTests.tearDown
    register_model = studio_fixture.StudioTests.register_model
    request = studio_fixture.StudioTests.request
    upload = studio_fixture.StudioTests.upload
    password = 'synthetic test passphrase only'

    def enter(self):
        response = self.client.post('/api/personal/setup', json={'password': self.password})
        self.assertEqual(response.status_code, 200, response.json)
        key = self.client.get_cookie('atelier_personal').value
        return self.store.sessions[key]

    def unlock(self, password=None):
        result = self.client.post('/api/personal/unlock', json={'password': password or self.password})
        self.assertEqual(result.status_code, 200, result.json)

    def test_encrypted_history_references_and_download_survive_lock(self):
        public = self.upload()
        session = self.enter()
        self.assertIsNone(session.asset(public['id']))
        project = self.client.post('/api/projects', json={'name': 'SECRET_PROJECT_MARKER', 'style_prompt': 'SECRET_STYLE_MARKER'}).json
        self.assertIn('id', project)
        reference = self.upload()
        with self.store.use(self.client.get_cookie('atelier_personal').value):
            image = save_image(self.store, Image.new('RGB', (16, 16), 'red'), project['id'], kind='generated', name='SECRET_NAME_MARKER', prompt='SECRET_PROMPT_MARKER')
        content = self.client.get(image['url'] + '?download=true')
        self.assertEqual(content.status_code, 200)
        self.assertTrue(content.data.startswith(b'\x89PNG'))
        self.assertEqual(content.headers['Cache-Control'], 'no-store')
        self.assertIn('attachment;', content.headers['Content-Disposition'])
        for file in self.store.vault.folder.rglob('*'):
            if file.is_file():
                self.assertNotIn(b'SECRET_', file.read_bytes())
                self.assertFalse(file.read_bytes().startswith(b'\x89PNG'))
        self.assertFalse((session.root / 'atelier.sqlite3').exists())
        self.assertEqual(list(session.assets.iterdir()), [])
        other = self.app.test_client()
        for path in (image['url'], '/api/assets/' + reference['id'], '/api/projects/' + project['id']):
            self.assertIn(other.get(path).status_code, (404, 405))
        self.client.post('/api/personal/lock')
        self.assertFalse(session.root.exists())
        self.assertEqual(self.client.get(image['url']).status_code, 404)
        self.unlock()
        self.assertEqual(self.client.get(image['url']).data, content.data)
        self.assertEqual(self.client.get('/api/projects').json[0]['name'], 'SECRET_PROJECT_MARKER')
        self.assertEqual(self.client.post('/api/temporary').status_code, 400)
        self.client.post('/api/personal/lock')

    def test_wrong_password_throttling_and_change(self):
        self.enter()
        changed = self.client.post('/api/personal/password', json={'current_password': self.password, 'password': 'a different synthetic passphrase'})
        self.assertEqual(changed.status_code, 200)
        self.client.post('/api/personal/lock')
        self.assertEqual(self.client.post('/api/personal/unlock', json={'password': self.password}).status_code, 400)
        self.unlock('a different synthetic passphrase')
        self.client.post('/api/personal/lock')
        for _ in range(5):
            self.assertEqual(self.client.post('/api/personal/unlock', json={'password': self.password}).status_code, 400)
        self.assertEqual(self.client.post('/api/personal/unlock', json={'password': 'a different synthetic passphrase'}).status_code, 429)

    def test_restart_requires_password_and_catalog_authentication(self):
        session = self.enter()
        reference = self.upload()
        cookie = self.client.get_cookie('atelier_personal').value
        self.client.post('/api/personal/lock')
        restarted = create_app(project_root=self.root, runtime_factory=FakeRuntime)
        client = restarted.test_client()
        client.set_cookie('atelier_personal', cookie)
        self.assertEqual(client.get('/api/assets').status_code, 423)
        client.post('/api/personal/lock')
        self.assertEqual(client.post('/api/personal/unlock', json={'password': self.password}).status_code, 200)
        self.assertTrue(client.get(reference['url']).data.startswith(b'\x89PNG'))
        client.post('/api/personal/lock')
        catalog = self.store.vault.folder / 'catalog.bin'
        data = bytearray(catalog.read_bytes()); data[30] ^= 1; catalog.write_bytes(data)
        response = self.client.post('/api/personal/unlock', json={'password': self.password})
        self.assertEqual(response.status_code, 400)
        self.assertIn('damaged', response.json['error'])

    def test_media_files_and_mesh_exports_are_encrypted(self):
        session = self.enter()
        mesh = self.client.post('/api/meshes/import', data={'mesh': (io.BytesIO(fixture_glb()), 'fixture.glb')})
        self.assertEqual(mesh.status_code, 201, mesh.json)
        exported = self.client.get('/api/meshes/' + mesh.json['id'] + '/export?format=glb')
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.data.startswith(b'glTF'))
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000); wav.writeframes(b'\0' * 32000)
        audio.seek(0)
        media = self.client.post('/api/videos/uploads', data={'media': (audio, 'test.wav')})
        self.assertEqual(media.status_code, 201, media.json)
        self.assertTrue(self.client.get(media.json['url']).data.startswith(b'RIFF'))
        self.assertEqual(list(session.assets.iterdir()), [])
        self.client.post('/api/personal/lock')
        self.unlock()
        self.assertTrue(self.client.get(media.json['url']).data.startswith(b'RIFF'))
        self.client.post('/api/personal/lock')

    def test_generation_isolated_and_lock_retains_completed_output(self):
        self.register_model()
        session = self.enter()
        self.runtime.gate.clear()
        reference = self.upload()
        result = self.client.post('/api/jobs', json=self.request(prompt='SECRET_GENERATION_MARKER', mode='edit', reference_ids=[reference['id']]))
        self.assertEqual(result.status_code, 202, result.json)
        deadline = time.monotonic() + 3
        while not self.runtime.calls and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.runtime.calls)
        self.client.post('/api/personal/lock')
        self.assertEqual(self.client.get('/api/jobs').json, [])
        self.runtime.gate.set()
        self.app.extensions['jobs'].queue.join()
        self.store.reap()
        self.assertFalse(session.root.exists())
        self.assertEqual(self.store.durable.all('SELECT * FROM jobs'), [])
        self.unlock()
        assets = self.client.get('/api/assets').json
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]['prompt'], 'SECRET_GENERATION_MARKER')
        self.client.post('/api/personal/lock')

    def test_expiry_stale_tabs_and_style_isolation(self):
        self.client.patch('/api/settings', json={'style_prompt': 'PUBLIC_STYLE'})
        session = self.enter()
        self.assertEqual(self.client.get('/api/settings').json['style_prompt'], '')
        self.client.patch('/api/settings', json={'style_prompt': 'SECRET_STYLE'})
        self.assertEqual(self.store.durable.setting('style_prompt'), 'PUBLIC_STYLE')
        response = self.client.post('/api/projects', json={'name': 'Wrong workspace'}, headers={'X-Atelier-Space': 'public'})
        self.assertEqual(response.status_code, 409)
        session.touched = time.monotonic() - 901
        self.assertEqual(self.client.get('/api/projects').status_code, 423)
        self.assertEqual(self.client.post('/api/jobs', json=self.request()).status_code, 423)
        self.assertFalse(session.root.exists())
        self.client.post('/api/personal/lock')

    def test_setup_and_password_endpoints_reject_cross_origin_and_short_passwords(self):
        self.assertEqual(self.client.post('/api/personal/setup', json={'password': 'short'}).status_code, 400)
        self.assertFalse(self.store.vault.configured)
        self.assertEqual(self.client.post('/api/personal/setup', json={'password': self.password}, headers={'Origin': 'https://example.com'}).status_code, 403)
        self.assertFalse(self.store.vault.configured)

    def test_blob_authentication_path_binding_and_scoped_inputs(self):
        session = self.enter()
        reference = self.upload()
        name = session.asset(reference['id'])['filename']
        with session.file_scope():
            path = session.input_path(name)
            self.assertTrue(path.is_file())
            with Image.open(path) as image:
                self.assertEqual(image.size, (120, 80))
        self.assertFalse(path.exists())
        with self.assertRaises(ValueError):
            session.read_file('../key.json')
        blob = session.blob(name)
        raw = bytearray(blob.read_bytes()); raw[-1] ^= 1; blob.write_bytes(raw)
        response = self.client.get(reference['url'])
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b'\x89PNG', response.data)
        self.client.post('/api/personal/lock')

    def test_cleanup_retries_transient_windows_file_lock(self):
        from atelier.vault import remove_work_tree
        folder = self.root / 'scratch'
        folder.mkdir()
        import shutil
        real_remove = shutil.rmtree
        attempts = []
        def remove(path, **kwargs):
            attempts.append(path)
            if len(attempts) == 1:
                raise PermissionError('Synthetic transient worker handle')
            return real_remove(path, **kwargs)
        with patch('atelier.vault.shutil.rmtree', side_effect=remove):
            remove_work_tree(folder, self.root)
        self.assertEqual(len(attempts), 2)
        self.assertFalse(folder.exists())
