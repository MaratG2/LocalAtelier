import io
import hashlib
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from atelier.app import create_app
from atelier.generation import save_image
from atelier.storage import now
from atelier.videos import validate_video
from atelier.providers.vdn_h3 import progress_event, remove_job_files


class IdleRuntime:
    def __init__(self, store):
        self.store = store
        self.active_model = None
        self.phase = 'Idle'
    def release(self, model_id=None):
        pass
    def logs(self):
        return {}


class VideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(project_root=self.root, runtime_factory=IdleRuntime)
        self.app.testing = True
        self.client = self.app.test_client()
        self.store = self.app.extensions['store']
        self.jobs = self.app.extensions['jobs']

    def tearDown(self):
        self.jobs.queue.join()
        self.temp.cleanup()

    def request(self, **kwargs):
        return {'prompt': 'A paper boat floats with gentle water sounds.', **kwargs}

    def image(self):
        return save_image(self.store, Image.new('RGB', (64, 64)), 'inbox', kind='generated', name='Paper boat')

    def audio(self, seconds=3):
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(8000)
            output.writeframes(b'\0\0' * (8000 * seconds))
        buffer.seek(0)
        return self.client.post('/api/videos/uploads', data={'media': (buffer, 'sound.wav')})

    def test_alignment_and_preview_quality(self):
        request = validate_video(self.request(seconds=5), self.store)
        self.assertEqual(request['frames'], 124)
        self.assertTrue(request['preview'])
        self.assertEqual(request['width'], 896)
        for bad in ({'seconds': True}, {'seconds': 30}, {'width': 999}, {'quality': []}, {'quality': 'high', 'preview': True}, {'preview': 'false'}, {'source_video_id': '../../x', 'mode': 'finish'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_video(self.request(**bad), self.store)

    def test_modes_and_reference_limits(self):
        image = self.image()
        valid = validate_video(self.request(mode='frames', first_id=image['id'], last_id=image['id']), self.store)
        self.assertEqual(valid['first_id'], image['id'])
        for bad in ({'mode': 'text', 'first_id': image['id']}, {'mode': 'frames'}, {'mode': 'references'}, {'mode': 'frames', 'first_id': image['id'], 'reference_ids': [image['id']]}, {'mode': 'references', 'reference_ids': [image['id'], image['id']]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_video(self.request(**bad), self.store)
        self.store.execute('UPDATE assets SET deleted=1 WHERE id=?', (image['id'],))
        with self.assertRaises(ValueError):
            validate_video(self.request(mode='frames', first_id=image['id']), self.store)

    def test_audio_upload_probe_and_duration_budget(self):
        response = self.audio(8)
        self.assertEqual(response.status_code, 201, response.json)
        audio = response.json
        self.assertEqual(audio['metadata']['media_kind'], 'audio')
        self.assertEqual(audio['metadata']['duration'], 8)
        self.assertEqual(audio['kind'], 'media-reference')
        with self.client.get(audio['thumbnail_url']) as response:
            self.assertEqual(response.status_code, 200)
        with self.client.get(audio['url']) as response:
            self.assertIn(response.mimetype, {'audio/wav', 'audio/x-wav'})
        with self.assertRaises(ValueError):
            validate_video(self.request(mode='frames', first_id=audio['id']), self.store)
        second = self.audio(8).json
        with self.assertRaises(ValueError):
            validate_video(self.request(mode='references', reference_ids=[audio['id'], second['id']]), self.store)
        self.assertEqual(self.audio(1).status_code, 400)

    def test_upload_rejects_playlist_and_unreadable_bytes(self):
        for name in ('remote.m3u8', 'broken.mp4'):
            self.assertEqual(self.client.post('/api/videos/uploads', data={'media': (io.BytesIO(b'not media'), name)}).status_code, 400)
        self.assertEqual(list(self.store.assets.iterdir()), [])

    def test_video_reference_not_accepted_by_image_or_mesh(self):
        asset = self.audio().json
        for endpoint, body in [('/api/jobs', {'model_id': 'qwen-image-2.1', 'mode': 'edit'}), ('/api/meshes/jobs', {'model_id': 'trellis2', 'mode': 'image-to-3d'})]:
            response = self.client.post(endpoint, json={**body, 'prompt': 'A boat', 'reference_ids': [asset['id']]})
            self.assertEqual(response.status_code, 400)
            self.assertIn('image', response.json['error'])

    def test_queue_model_guard_and_success_registration(self):
        self.assertEqual(self.client.post('/api/videos/jobs', json=self.request()).status_code, 400)
        self.store.execute('INSERT INTO models(id,source,runtime_path,linked,verified) VALUES(?,?,?,?,?)', ('vdn-h3', 'managed', str(self.root / 'models/vdn-h3'), now(), now()))
        with patch('atelier.providers.vdn_h3.generate', return_value={'id': 'unit-fixture-video'}) as generate:
            response = self.client.post('/api/videos/jobs', json=self.request())
            self.assertEqual(response.status_code, 202)
            self.jobs.queue.join()
            job = self.store.job(response.json['id'])
            self.assertEqual(job['status'], 'complete')
            self.assertEqual(job['result_ids'], ['unit-fixture-video'])
            self.assertEqual(generate.call_args.args[1]['frames'], 124)

    def test_finish_uses_saved_settings_and_protects_parent(self):
        image = self.image(); asset_id = image['id']
        settings = validate_video(self.request(), self.store)
        folder = self.store.assets / asset_id; (folder / 'video.artifacts').mkdir(parents=True)
        for name in ('first-pass.pt', 'first-pass.engine.json', 'video.json', 'conditioning.pt'):
            (folder / 'video.artifacts' / name).write_text('unit fixture')
        self.store.execute('UPDATE assets SET kind=?,model_id=?,filename=?,metadata=? WHERE id=?', ('video', 'vdn-h3', f'{asset_id}/video.mp4', json.dumps({'preview': True, 'settings': settings}), asset_id))
        request = validate_video({'mode': 'finish', 'source_video_id': asset_id}, self.store)
        self.assertFalse(request['preview'])
        self.assertEqual(request['prompt'], settings['prompt'])
        self.assertEqual(request['seed'], settings['seed'])
        with self.assertRaises(ValueError):
            validate_video({'mode': 'finish', 'source_video_id': asset_id, 'seed': 99}, self.store)
        self.store.execute("INSERT INTO jobs(id,project_id,model_id,status,phase,total,request,created,updated) VALUES('test','inbox','vdn-h3','queued','Queued',1,?,?,?)", (json.dumps(request), now(), now()))
        self.assertEqual(self.client.patch('/api/assets/'+asset_id, json={'deleted': True}).status_code, 400)
        self.store.execute("UPDATE jobs SET status='cancelled' WHERE id='test'")
        self.assertEqual(self.client.get('/api/assets?kind=video').json[0]['id'], asset_id)
        self.assertEqual(self.client.get('/api/projects').json[0]['asset_count'], 1)

    def test_progress_ignores_unrelated_events(self):
        self.assertIsNone(progress_event({'event': 'unknown'}))
        self.assertEqual(progress_event({'event': 'step', 'step': 3, 'steps': 8})[1], 38)
        self.assertEqual(progress_event({'event': 'encoding_start'})[0], 'Encoding prompt and references')

    def test_cleanup_waits_for_closing_worker_log(self):
        folder = self.root / 'cancelled-job'
        folder.mkdir()
        handle = (folder / 'worker.log').open('w')
        handle.write('Owned worker output'); handle.flush()
        # An open log cannot be unlinked on Windows until its writer closes it.
        closer = threading.Timer(.1, handle.close)
        closer.start()
        try:
            remove_job_files(folder)
            self.assertFalse(folder.exists())
        finally:
            closer.join()
            handle.close()

    def test_corrupt_h3_weights_clear_verification(self):
        root = self.root / 'models/vdn-h3'
        (root / 'weights').mkdir(parents=True)
        (root / 'weights/test.safetensors').write_bytes(b'bad')
        self.store.execute('INSERT INTO models(id,source,runtime_path,linked,verified) VALUES(?,?,?,?,?)', ('vdn-h3', 'managed', str(root), now(), now()))
        row = {'target': 'test.safetensors', 'bytes': 3, 'sha256': hashlib.sha256(b'new').hexdigest()}
        with patch('atelier.video_install.manifest', return_value={'files': [row]}):
            with self.assertRaisesRegex(RuntimeError, 'Integrity mismatch'):
                self.app.extensions['models']._verify({'model_id': 'vdn-h3', 'logs': []})
        self.assertIsNone(self.app.extensions['models'].record('vdn-h3')['verified'])


if __name__ == '__main__':
    unittest.main()
