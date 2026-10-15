import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from atelier.app import create_app
from atelier.lifecycle import write_json
from atelier.providers import vdn_h3
from atelier.runtime import Runtime
from atelier.storage import now


class StubProcess:
    alive = True

    def poll(self):
        return None if self.alive else 0


class SessionRuntime(Runtime):
    """Exercise the real H3/session ownership code without a CUDA subprocess."""
    def __init__(self, store):
        self.starts, self.releases = 0, 0
        super().__init__(store)

    def _start(self, args, cwd, env, name):
        self.starts += 1
        folder = Path(args[args.index('--folder') + 1])
        write_json(folder / 'ready.json', {'pid': 1})
        process = StubProcess()
        self.processes.append(process)
        return process

    def release(self, model_id=None):
        if model_id and self.active_model != model_id:
            return
        if self.processes:
            self.releases += 1
        for process in self.processes:
            process.alive = False
        self.processes.clear()
        self.active_model = self.worker_root = self.h3_session = None
        self.phase = 'Idle'


class H3RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(project_root=self.root, runtime_factory=SessionRuntime)
        self.client = self.app.test_client()
        self.store, self.runtime = (self.app.extensions[k] for k in ('store', 'runtime'))
        self.bundle = self.root / 'models/vdn-h3'
        (self.bundle / '.runtime').mkdir(parents=True)
        self.store.execute('INSERT INTO models(id,source,runtime_path,linked,verified) VALUES(?,?,?,?,?)',
                           ('vdn-h3', 'managed', str(self.bundle), now(), now()))
        self.failed = False
        self.commands = []
        self.patches = [patch.object(vdn_h3, 'complete', return_value=True),
                        patch.object(vdn_h3, 'write_json', side_effect=self.submit),
                        patch.object(vdn_h3, 'inspect_media', return_value=dict(media_kind='video', has_audio=True,
                                     width=512, height=512, duration=2.33, frames=56, fps=24)),
                        patch('atelier.videos.thumbnails', side_effect=self.thumbnails)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        self.app.extensions['jobs'].queue.join()
        self.runtime.release()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def thumbnails(self, path, folder, info):
        Image.new('RGB', (32, 32), '#44634f').save(folder / 'poster.png')

    def submit(self, path, value):
        self.commands.append(value)
        arguments = value['arguments']
        output = Path(arguments[arguments.index('--out') + 1])
        output.write_bytes(b'synthetic video fixture')
        write_json(output.with_suffix('.request.json'), {'success': not self.failed, 'error_message': 'fixture failure'})
        write_json(Path(path).with_name('response.json'), {'id': value['id'], 'returncode': int(self.failed)})

    def render(self):
        response = self.client.post('/api/videos/jobs', json=dict(prompt='A paper boat on calm water',
                                    width=512, height=512, seconds=2, preview=True))
        self.assertEqual(response.status_code, 202, response.json)
        self.app.extensions['jobs'].queue.join()
        return next(row for row in self.client.get('/api/jobs').json if row['id'] == response.json['id'])

    def test_personal_videos_reuse_worker_and_lock_releases_it(self):
        self.client.post('/api/personal/setup', json={'password': 'synthetic video retention password'})
        key = self.client.get_cookie('atelier_personal').value
        session = self.store.sessions[key]
        for _ in range(2):
            self.assertEqual(self.render()['status'], 'complete')
        self.assertEqual((self.runtime.starts, self.runtime.releases), (1, 0))
        self.assertEqual(self.runtime.worker_root, session.root / 'runtime')
        self.assertEqual(self.runtime.active_model, 'vdn-h3')
        self.assertEqual(list(session.assets.iterdir()), [])
        self.assertIn('--no-tuning', self.commands[0]['arguments'])
        self.assertEqual(len(self.client.get('/api/assets?kind=video').json), 2)
        self.client.post('/api/personal/lock')
        self.assertEqual(self.runtime.releases, 1)
        self.assertFalse(session.root.exists())

    def test_incognito_and_public_do_not_share_resident_session(self):
        self.assertEqual(self.render()['status'], 'complete')
        self.client.post('/api/temporary')
        self.assertEqual(self.render()['status'], 'complete')
        self.assertEqual(self.render()['status'], 'complete')
        self.assertEqual((self.runtime.starts, self.runtime.releases), (2, 1))
        self.client.delete('/api/temporary')
        self.assertIsNone(self.runtime.active_model)
        self.assertEqual(self.runtime.releases, 2)

    def test_explicit_unload_and_failure_release_video_worker(self):
        self.store.set_setting('unload_after_job', True)
        self.assertEqual(self.render()['status'], 'complete')
        self.assertIsNone(self.runtime.active_model)
        self.store.set_setting('unload_after_job', False)
        self.failed = True
        self.assertEqual(self.render()['status'], 'error')
        self.assertIsNone(self.runtime.active_model)
        self.assertEqual((self.runtime.starts, self.runtime.releases), (2, 2))

    def test_cancel_stops_session_before_removing_outputs(self):
        request = dict(prompt='A paper boat', width=512, height=512, frames=56, seed=42,
                       quality='light', preview=True, reference_ids=[], project_id='inbox')
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            vdn_h3.generate(self.runtime, request, lambda *_: None, unittest.mock.Mock(side_effect=[False, True]))
        self.assertIsNone(self.runtime.active_model)
        self.assertEqual(list(self.store.assets.iterdir()), [])

    def test_reports_real_resident_model_cache_hits(self):
        self.assertEqual(vdn_h3.progress_event({'event': 'loaded', 'resident_cache_hit': True}),
                         ('Reusing loaded video model', 0))
