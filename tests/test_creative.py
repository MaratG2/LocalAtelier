import io
import json
import unittest
import zipfile
import wave
from unittest.mock import patch

from PIL import Image

from test_studio import StudioTests as StudioFixture
from atelier.generation import save_image
from atelier.access_log import PrivateRequestHandler


class CreativeTests(unittest.TestCase):
    setUp = StudioFixture.setUp
    tearDown = StudioFixture.tearDown
    register_model = StudioFixture.register_model
    request = StudioFixture.request
    upload = StudioFixture.upload

    def test_access_log_omits_private_search_queries(self):
        handler = object.__new__(PrivateRequestHandler)
        handler.path = '/api/assets?q=PRIVATE_SEARCH_MARKER&project=inbox'
        handler.command = 'GET'
        handler.request_version = 'HTTP/1.1'
        with patch.object(handler, 'log') as log:
            handler.log_request(200, 150)
        args = log.call_args.args
        rendered = args[1] % args[2:]
        self.assertEqual(rendered, '"GET /api/assets HTTP/1.1" 200 150')
        self.assertNotIn('PRIVATE_SEARCH_MARKER', rendered)

    def wait_job(self, job_id):
        self.app.extensions['jobs'].queue.join()
        return next(j for j in self.client.get('/api/jobs').json if j['id'] == job_id)

    def test_temporary_generation_never_enters_durable_history(self):
        self.register_model()
        self.assertEqual(self.client.post('/api/temporary').status_code, 200)
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        uploaded = self.upload()
        response = self.client.post('/api/jobs', json=self.request(prompt='PRIVATE_MARKER', mode='edit', reference_ids=[uploaded['id']]))
        self.assertEqual(response.status_code, 202, response.json)
        job = self.wait_job(response.json['id'])
        self.assertEqual(job['status'], 'complete', job)
        result = self.client.get('/api/assets').json[0]
        self.assertTrue(result['temporary'])
        download = self.client.get(result['url'] + '?download=true')
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers['Cache-Control'], 'no-store')
        download.close()
        self.assertEqual(self.store.durable.all('SELECT * FROM jobs'), [])
        self.assertEqual(self.store.durable.all('SELECT * FROM assets'), [])
        self.assertFalse((folder / 'atelier.sqlite3').exists())
        self.assertEqual(self.client.delete('/api/temporary').status_code, 200)
        self.assertFalse(folder.exists())
        self.assertEqual(self.client.get('/api/jobs').json, [])
        self.assertEqual(self.client.get(result['url']).status_code, 404)
        self.assertNotIn(b'PRIVATE_MARKER', (self.store.durable.root / 'atelier.sqlite3').read_bytes())

    def test_temporary_session_isolation_and_active_job_protection(self):
        self.register_model()
        other = self.app.test_client()
        self.client.post('/api/temporary')
        self.runtime.gate.clear()
        response = self.client.post('/api/jobs', json=self.request())
        self.assertEqual(response.status_code, 202)
        self.assertEqual(other.get('/api/jobs').json, [])
        self.assertEqual(other.post('/api/runtime/release').status_code, 400)
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        self.client.delete('/api/temporary')
        self.runtime.gate.set()
        self.app.extensions['jobs'].queue.join()
        self.store.reap()
        self.assertFalse(folder.exists())
        self.assertEqual(self.store.durable.all('SELECT * FROM jobs'), [])

    def test_temporary_saved_references_are_read_only_and_available(self):
        saved = self.upload()
        self.client.post('/api/temporary')
        response = self.client.get(saved['url'])
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.patch('/api/assets/' + saved['id'], json={'deleted': True}).status_code, 400)
        self.assertEqual(self.client.post('/api/projects', json={'name': 'Private'}).status_code, 400)
        self.client.delete('/api/temporary')
        self.assertFalse(self.store.asset(saved['id'])['deleted'])

    def test_temporary_mesh_and_audio_uploads_are_disposed(self):
        from test_meshes import fixture_glb
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        folder = self.store.sessions[key].root
        mesh = self.client.post('/api/meshes/import', data={'mesh': (io.BytesIO(fixture_glb()), 'test.glb')})
        self.assertEqual(mesh.status_code, 201, mesh.json)
        sound = io.BytesIO()
        with wave.open(sound, 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
            stream.writeframes(b'\x00\x00' * 16000)
        sound.seek(0)
        audio = self.client.post('/api/videos/uploads', data={'media': (sound, 'test.wav')})
        self.assertEqual(audio.status_code, 201, audio.json)
        self.assertEqual(self.store.durable.all('SELECT * FROM assets'), [])
        exported = self.client.get(f"/api/meshes/{mesh.json['id']}/export?format=glb")
        self.assertEqual(exported.status_code, 200)
        exported.close()
        self.client.delete('/api/temporary')
        self.assertFalse(folder.exists())

    def test_qwen_private_worker_routes_all_content_directories_to_session(self):
        from atelier.runtime import Runtime
        self.register_model()
        self.client.post('/api/temporary')
        key = self.client.get_cookie('atelier_temporary').value
        calls = []
        runtime = Runtime(self.store)
        with self.store.use(key), patch('atelier.runtime.installed', return_value=True), patch('atelier.runtime.socket.socket'), patch.object(runtime, '_wait'), patch.object(runtime, '_start', side_effect=lambda args, cwd, env, name: calls.append((args, env))):
            runtime.ensure('qwen-image-2.1', lambda *args: None)
            for flag in ('--output-directory', '--input-directory', '--temp-directory', '--user-directory'):
                args = calls[0][0]
                self.assertTrue(args[args.index(flag) + 1].is_relative_to(self.store.root))
            self.assertEqual(calls[0][1]['TEMP'], str(self.store.root / 'runtime/temp'))
            self.assertIn('--disable-metadata', calls[0][0])
        runtime.release()
        self.client.delete('/api/temporary')

    def test_styles_snapshot_prompt_and_reference_with_overrides(self):
        self.register_model()
        ref = self.upload()
        project = self.client.post('/api/projects', json={'name': 'Pixel game', 'style_prompt': 'Crisp pixel art', 'style_reference_id': ref['id']}).json
        response = self.client.post('/api/jobs', json=self.request(project_id=project['id'], prompt='A knight'))
        job = self.wait_job(response.json['id'])
        self.assertEqual(job['request']['mode'], 'reference')
        self.assertEqual(job['request']['reference_ids'], [ref['id']])
        self.assertIn('Crisp pixel art', job['request']['prompt'])
        self.assertEqual(job['request']['user_prompt'], 'A knight')
        asset = self.store.asset(job['result_ids'][0])
        self.assertEqual(asset['prompt'], 'A knight')
        override = self.client.post('/api/jobs', json=self.request(project_id=project['id'], use_style=False, use_style_reference=False))
        plain = self.wait_job(override.json['id'])['request']
        self.assertEqual(plain['mode'], 't2i')
        self.assertEqual(plain['reference_ids'], [])
        self.assertNotIn('Crisp pixel art', plain['prompt'])
        edit = self.client.post('/api/jobs', json=self.request(project_id=project['id'], mode='edit', reference_ids=[ref['id']]))
        self.assertEqual(self.wait_job(edit.json['id'])['request']['reference_ids'], [ref['id']])

    def test_global_style_inheritance_and_invalid_project_atomicity(self):
        self.register_model()
        self.client.patch('/api/settings', json={'style_prompt': 'Warm watercolor'})
        job = self.client.post('/api/jobs', json=self.request()).json
        self.assertIn('Warm watercolor', self.wait_job(job['id'])['request']['prompt'])
        self.client.patch('/api/projects/inbox', json={'inherit_style': False})
        job = self.client.post('/api/jobs', json=self.request()).json
        self.assertNotIn('Warm watercolor', self.wait_job(job['id'])['request']['prompt'])
        before = len(self.store.projects())
        self.assertEqual(self.client.post('/api/projects', json={'name': 'Bad', 'style_reference_id': 'missing'}).status_code, 400)
        self.assertEqual(len(self.store.projects()), before)

    def test_game_export_exact_cells_alpha_and_tiled_map(self):
        source = Image.new('RGBA', (128, 64), (255, 0, 0, 0))
        source.paste((0, 200, 0, 255), (64, 0, 128, 64))
        tool = {'kind': 'tileset', 'columns': 2, 'rows': 1, 'cell_size': 32, 'palette': 16, 'pixel_art': True, 'fps': 8}
        asset = save_image(self.store, source, 'inbox', kind='generated', name='Tiles', metadata={'game_asset': tool})
        response = self.client.post(f"/api/assets/{asset['id']}/game-export", json={'layout': [1, 2] * 72})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            with Image.open(io.BytesIO(archive.read('atlas.png'))) as atlas:
                self.assertEqual(atlas.size, (64, 32))
                self.assertEqual(atlas.getpixel((0, 0))[3], 0)
                self.assertEqual(atlas.getpixel((40, 0))[3], 255)
            self.assertEqual(len(json.loads(archive.read('atlas.json'))['frames']), 2)
            tilemap = json.loads(archive.read('map.tmj'))
            self.assertEqual(tilemap['layers'][0]['data'], [1, 2] * 72)
            self.assertEqual(json.loads(archive.read('tileset.tsj'))['tilewidth'], 32)
        invalid = self.client.post(f"/api/assets/{asset['id']}/game-export", json={'layout': [3] * 144})
        self.assertEqual(invalid.status_code, 400)

    def test_game_generation_adds_grid_without_overwriting_user_prompt(self):
        self.register_model()
        response = self.client.post('/api/jobs', json=self.request(prompt='Walking fox', game_asset={'kind': 'spritesheet', 'columns': 4, 'rows': 2}))
        job = self.wait_job(response.json['id'])
        self.assertIn('Exactly 4 columns and 2 rows', job['request']['prompt'])
        self.assertEqual((job['request']['width'], job['request']['height']), (1024, 512))
        asset = self.store.asset(job['result_ids'][0])
        self.assertEqual(asset['prompt'], 'Walking fox')
        self.assertEqual(asset['metadata']['game_asset']['cell_size'], 32)


if __name__ == '__main__':
    unittest.main()

# Keep imported fixture out of unittest discovery.
del StudioFixture
